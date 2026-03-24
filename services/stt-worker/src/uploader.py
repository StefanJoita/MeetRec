# services/stt-worker/src/uploader.py
# ============================================================
# Database Uploader — scrie rezultatele transcrierii în PostgreSQL
# ============================================================

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import asyncpg
import structlog

from src.config import settings

logger = structlog.get_logger(__name__)


# ── Structura pentru metadate transcript ─────────────────────

@dataclass
class TranscriptMetadata:
    """
    Date agregate despre transcript — calculate după transcriere.
    Pasate la save_results() pentru a actualiza tabela transcripts.
    """
    word_count: int            # numărul total de cuvinte
    confidence_avg: float      # media confidence per segment (0.0 - 1.0)
    processing_time_sec: int   # cât a durat transcrierea (secunde)
    language: str              # "ro", "en", etc.
    model_used: str            # "whisper-medium", "whisper-large-v3"


# ── DatabaseUploader ─────────────────────────────────────────

class DatabaseUploader:
    """
    Gestionează toate operațiunile DB din stt-worker.
    Pattern: pool de conexiuni asyncpg, tranzacții explicite.
    """

    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None

    # ── Lifecycle ─────────────────────────────────────────────

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=1,
            max_size=3,
            command_timeout=60,
        )
        logger.info("db_connected", min_size=1, max_size=3)

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.close()
            logger.info("db_disconnected")

    # ── Query helpers ─────────────────────────────────────────

    async def get_transcript_id(self, recording_id: str) -> Optional[str]:
        """Returnează UUID-ul transcriptului asociat înregistrării."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM transcripts WHERE recording_id = $1",
                recording_id,
            )
        if not row:
            logger.error("transcript_not_found", recording_id=recording_id)
            return None
        return str(row["id"])

    async def get_transcript_index_offset(self, transcript_id: str) -> int:
        """
        Returnează primul segment_index disponibil pentru acest transcript.

        Folosit pentru sesiuni multi-part: Whisper numerotează segmentele
        de la 0 pentru fiecare fișier audio. Dacă fișierul 1 a produs
        segmente 0..47, fișierul 2 trebuie să înceapă de la 48 pentru a
        nu suprascrie segmentele existente.

        Exemplu:
            transcript are segmente 0..47  → returnează 48
            transcript fără segmente încă  → returnează 0
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COALESCE(MAX(segment_index) + 1, 0) AS next_index
                FROM transcript_segments
                WHERE transcript_id = $1
                """,
                transcript_id,
            )
        return row["next_index"]

    async def get_time_offset_seconds(
        self, recording_id: str, audio_segment_index: int
    ) -> float:
        """
        Returnează offset-ul de timp (în secunde) pentru un segment suplimentar.

        Whisper produce timestamps relative la începutul fișierului audio.
        Pentru un transcript unificat, timestamps-urile trebuie să fie
        continue: fișierul 2 începe de unde s-a terminat fișierul 1.

        audio_segment_index=1 → offset = durata înregistrării principale (segment 0)
        audio_segment_index=2 → offset = durata segment 0 + durata segment 1
        etc.

        Duratele vin din:
            - recordings.duration_seconds  (fișierul principal, segment 0)
            - recording_audio_segments.duration_seconds  (segmentele 1, 2, ...)
        """
        async with self._pool.acquire() as conn:
            # Durata fișierului principal (segment 0 = recordings.duration_seconds)
            main_row = await conn.fetchrow(
                "SELECT COALESCE(duration_seconds, 0) AS dur FROM recordings WHERE id = $1",
                recording_id,
            )
            main_dur = float(main_row["dur"] or 0)

            if audio_segment_index == 1:
                return main_dur

            # Suma duratelor segmentelor intermediare (1 .. audio_segment_index - 1)
            extra_row = await conn.fetchrow(
                """
                SELECT COALESCE(SUM(duration_seconds), 0) AS dur
                FROM recording_audio_segments
                WHERE recording_id = $1 AND segment_index < $2
                """,
                recording_id,
                audio_segment_index,
            )
            extra_dur = float(extra_row["dur"] or 0)
            return main_dur + extra_dur

    async def mark_processing(
        self,
        transcript_id: str,
        recording_id: str,
        model_name: str,
    ) -> None:
        """Marchează jobul ca 'în procesare' în ambele tabele."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE transcripts
                    SET status = 'processing',
                        started_at = NOW(),
                        model_used = $2
                    WHERE id = $1
                    """,
                    transcript_id,
                    model_name,
                )
                await conn.execute(
                    """
                    UPDATE recordings
                    SET status = 'transcribing',
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                    recording_id,
                )
        logger.info("marked_processing", transcript_id=transcript_id)

    async def save_results(
        self,
        transcript_id: str,
        recording_id: str,
        segments: list,
        metadata: TranscriptMetadata,
        index_offset: int = 0,
        time_offset_sec: float = 0.0,
        segment_id: Optional[str] = None,
    ) -> None:
        """
        Salvează rezultatele transcrierii și actualizează statusul.

        Parametri pentru sesiuni multi-part:
            index_offset    — adăugat la segment_index din Whisper, evită conflicte
                              pe UNIQUE (transcript_id, segment_index)
            time_offset_sec — adăugat la start_time/end_time, face timestamps continue
            segment_id      — ID din recording_audio_segments; dacă prezent,
                              marchează segmentul ca 'completed' și verifică
                              dacă toată sesiunea e finalizată

        Logica de completare:
            Fișier simplu (segment_id=None):
                → recording + transcript = 'completed' imediat
            Sesiune multi-part (segment_id prezent):
                → marchează recording_audio_segments[segment_id] = 'completed'
                → dacă TOATE segmentele suplimentare sunt 'completed' ȘI
                   fișierul principal are deja segmente în transcript:
                       recording + transcript = 'completed'
                → altfel: recording rămâne 'transcribing' (mai vin segmente)
        """
        segment_tuples = [
            (
                str(uuid.uuid4()),
                transcript_id,
                seg.segment_index + index_offset,   # offset pentru sesiuni multi-part
                seg.start_time + time_offset_sec,   # timestamps continue
                seg.end_time + time_offset_sec,
                seg.text,
                seg.confidence,
                seg.language,
            )
            for seg in segments
        ]

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # ── 1. Bulk insert segmente ───────────────────────────
                await conn.executemany(
                    """
                    INSERT INTO transcript_segments
                        (id, transcript_id, segment_index, start_time,
                         end_time, text, confidence, language)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (transcript_id, segment_index) DO NOTHING
                    """,
                    segment_tuples,
                )

                # ── 2. Actualizăm statusul ────────────────────────────
                if segment_id is not None:
                    # Job pentru segment suplimentar: marchează-l ca terminat
                    await conn.execute(
                        """
                        UPDATE recording_audio_segments
                        SET status = 'completed'
                        WHERE id = $1
                        """,
                        segment_id,
                    )
                    # Verificăm dacă mai sunt segmente în așteptare
                    pending_count = await conn.fetchval(
                        """
                        SELECT COUNT(*) FROM recording_audio_segments
                        WHERE recording_id = $1 AND status != 'completed'
                        """,
                        recording_id,
                    )
                    # Verificăm dacă fișierul principal a fost deja transcris
                    main_segments_count = await conn.fetchval(
                        """
                        SELECT COUNT(*) FROM transcript_segments
                        WHERE transcript_id = $1
                        """,
                        transcript_id,
                    )
                    all_done = (pending_count == 0 and main_segments_count > 0)
                else:
                    # Job principal: verificăm dacă mai sunt segmente suplimentare neprocesate
                    pending_count = await conn.fetchval(
                        """
                        SELECT COUNT(*) FROM recording_audio_segments
                        WHERE recording_id = $1 AND status != 'completed'
                        """,
                        recording_id,
                    )
                    all_done = (pending_count == 0)

                if all_done:
                    # Toată sesiunea e completă — recalculăm metadatele din toate segmentele
                    agg = await conn.fetchrow(
                        """
                        SELECT
                            COALESCE(SUM(
                                array_length(string_to_array(trim(text), ' '), 1)
                            ), 0) AS word_count,
                            COALESCE(AVG(confidence), 0.0) AS confidence_avg
                        FROM transcript_segments
                        WHERE transcript_id = $1
                        """,
                        transcript_id,
                    )
                    await conn.execute(
                        """
                        UPDATE transcripts
                        SET status = 'completed',
                            completed_at = NOW(),
                            word_count = $2,
                            confidence_avg = $3,
                            processing_time_sec = $4,
                            language = $5
                        WHERE id = $1
                        """,
                        transcript_id,
                        agg["word_count"],
                        round(float(agg["confidence_avg"]), 3),
                        metadata.processing_time_sec,
                        metadata.language,
                    )
                    await conn.execute(
                        """
                        UPDATE recordings
                        SET status = 'completed', updated_at = NOW()
                        WHERE id = $1
                        """,
                        recording_id,
                    )
                    logger.info(
                        "session_completed",
                        recording_id=recording_id,
                        word_count=agg["word_count"],
                    )
                else:
                    # Sesiunea nu e completă — rămâne în 'transcribing'
                    await conn.execute(
                        """
                        UPDATE recordings
                        SET status = 'transcribing', updated_at = NOW()
                        WHERE id = $1
                        """,
                        recording_id,
                    )

        logger.info(
            "results_saved",
            transcript_id=transcript_id,
            segments_count=len(segments),
            index_offset=index_offset,
            time_offset_sec=time_offset_sec,
            segment_id=segment_id,
        )

    async def mark_failed(
        self,
        transcript_id: str,
        recording_id: str,
        error_message: str,
    ) -> None:
        """Marchează jobul ca eșuat cu mesajul de eroare."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE transcripts
                    SET status = 'failed',
                        error_message = $2,
                        completed_at = NOW()
                    WHERE id = $1
                    """,
                    transcript_id,
                    error_message,
                )
                await conn.execute(
                    """
                    UPDATE recordings
                    SET status = 'failed',
                        error_message = $2,
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                    recording_id,
                    error_message,
                )
        logger.warning(
            "job_failed",
            transcript_id=transcript_id,
            error=error_message[:200],
        )
