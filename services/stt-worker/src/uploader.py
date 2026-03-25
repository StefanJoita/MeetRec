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

    # ── Session Assembly ──────────────────────────────────────

    async def get_all_session_segments(self, recording_id: str) -> list:
        """
        Returnează toate căile audio ale unei sesiuni, sortate după segment_index.

        Ordinea rezultată:
          [0] recordings.file_path          ← fișierul principal (segment_index=0)
          [1] recording_audio_segments[1]   ← segment_index=1
          [2] recording_audio_segments[2]   ← segment_index=2
          ...

        Folosit de AudioAssembler pentru a ști ce fișiere să concateneze și în ce ordine.
        Ordinea după segment_index garantează timestamps corecte indiferent de ordinea
        în care au sosit segmentele la server.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT file_path, 0 AS segment_index
                FROM recordings
                WHERE id = $1

                UNION ALL

                SELECT file_path, segment_index
                FROM recording_audio_segments
                WHERE recording_id = $1

                ORDER BY segment_index ASC
                """,
                recording_id,
            )
        from pathlib import Path
        return [Path(row["file_path"]) for row in rows]

    async def save_session_results(
        self,
        transcript_id: str,
        recording_id: str,
        segments: list,
        metadata: "TranscriptMetadata",
        merged_file_path: Optional[str] = None,
    ) -> None:
        """
        Salvează rezultatele transcrierii unei sesiuni complete (audio concatenat).

        Spre deosebire de save_results() care gestionează sesiuni multi-part
        cu verificări de pending_count, aceasta marchează direct tot ca 'completed':
        - Am transcris întregul audio concatenat → nu mai sunt segmente în așteptare
        - Nu există recording_audio_segments de marcat (am transcris fișierul concatenat temp)
        """
        segment_tuples = [
            (
                str(uuid.uuid4()),
                transcript_id,
                seg.segment_index,
                seg.start_time,
                seg.end_time,
                seg.text,
                seg.confidence,
                seg.language,
            )
            for seg in segments
        ]

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # ── 1. Inserăm segmentele ─────────────────────────────
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

                # ── 2. Marcăm toate segmentele audio ca 'completed' ───
                # save_results() marchează segmentele individuale, dar calea
                # de sesiune transcrie fișierul concatenat fără a trece prin
                # save_results — le marcăm explicit aici.
                await conn.execute(
                    """
                    UPDATE recording_audio_segments
                    SET status = 'completed'
                    WHERE recording_id = $1
                    """,
                    recording_id,
                )

                # ── 3. Marcăm transcript ca 'completed' ───────────────
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
                    metadata.word_count,
                    round(metadata.confidence_avg, 3),
                    metadata.processing_time_sec,
                    metadata.language,
                )

                # ── 4. Marcăm recording ca 'completed', actualizăm durata și calea audio ──
                # Durata reală = suma duratelor măsurate de ingest din fișierele audio,
                # NU din end_time-ul Whisper (care poate supraevalua ultimul segment).
                dur_row = await conn.fetchrow(
                    """
                    SELECT r.duration_seconds + COALESCE(SUM(ras.duration_seconds), 0) AS total
                    FROM recordings r
                    LEFT JOIN recording_audio_segments ras ON ras.recording_id = r.id
                    WHERE r.id = $1
                    GROUP BY r.duration_seconds
                    """,
                    recording_id,
                )
                total_duration = int(dur_row["total"] or 0)
                if merged_file_path:
                    await conn.execute(
                        """
                        UPDATE recordings
                        SET status = 'completed',
                            updated_at = NOW(),
                            duration_seconds = $2,
                            file_path = $3,
                            audio_format = 'wav'
                        WHERE id = $1
                        """,
                        recording_id,
                        total_duration,
                        merged_file_path,
                    )
                else:
                    await conn.execute(
                        """
                        UPDATE recordings
                        SET status = 'completed',
                            updated_at = NOW(),
                            duration_seconds = $2
                        WHERE id = $1
                        """,
                        recording_id,
                        total_duration,
                    )

        logger.info(
            "session_results_saved",
            transcript_id=transcript_id,
            recording_id=recording_id,
            segments_count=len(segments),
            word_count=metadata.word_count,
            total_duration_sec=total_duration,  # din audio files, nu din Whisper
            merged_file_path=merged_file_path,
        )
