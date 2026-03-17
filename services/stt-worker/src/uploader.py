# services/stt-worker/src/uploader.py
# ============================================================
# Database Uploader — scrie rezultatele transcrierii în PostgreSQL
# ============================================================
# Folosim asyncpg direct (nu SQLAlchemy ORM) din același motiv
# ca în ingest: control fin, query-uri explicite, performanță.
#
# Responsabilitățile acestei clase:
#   1. Marchează transcript ca "processing" când jobul începe
#   2. Inserează segmentele în bulk după transcriere
#   3. Actualizează statusul final (completed sau failed)
#
# Pattern asyncpg (identic cu ingest):
#   pool = await asyncpg.create_pool(dsn=...)
#   async with pool.acquire() as conn:
#       async with conn.transaction():
#           await conn.execute(query, $1, $2, ...)
#           await conn.executemany(query, list_of_tuples)
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
        """
        Creează pool-ul de conexiuni PostgreSQL.
        Apelat o singură dată la startup.

        min_size=1, max_size=3:
        STT Worker-ul procesează 1 job la un timp (single-concurrency).
        Nu avem nevoie de 10 conexiuni ca în API — 3 sunt mai mult decât suficiente.
        """
        self._pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=1,
            max_size=3,
            command_timeout=60,  # query-urile de INSERT pot dura mai mult
        )
        logger.info("db_connected", min_size=1, max_size=3)

    async def disconnect(self) -> None:
        """Închide pool-ul la shutdown. Așteaptă ca query-urile active să termine."""
        if self._pool:
            await self._pool.close()
            logger.info("db_disconnected")

    # ── Query helpers ─────────────────────────────────────────

    async def get_transcript_id(self, recording_id: str) -> Optional[str]:
        """
        Returnează UUID-ul transcriptului asociat înregistrării.

        Ingest-ul creează rândul din transcripts cu status='pending'.
        Noi avem nevoie de transcript_id pentru a insera segmentele.

        Returns:
            UUID ca string, sau None dacă nu există (eroare de consistență).
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM transcripts WHERE recording_id = $1",
                recording_id,
            )
        if not row:
            logger.error("transcript_not_found", recording_id=recording_id)
            return None
        return str(row["id"])

    async def mark_processing(
        self,
        transcript_id: str,
        recording_id: str,
        model_name: str,
    ) -> None:
        """
        Marchează jobul ca 'în procesare' în ambele tabele.

        Cele două UPDATE-uri sunt în aceeași tranzacție:
        dacă unul eșuează, ambele se rollback → consistență garantată.

        De ce actualizăm și recordings?
        UI-ul citește din recordings.status pentru a afișa progresul.
        'transcribing' arată utilizatorului că jobul e activ.
        """
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
        segments: list,   # List[TranscriptSegment] — importul circular evitat
        metadata: TranscriptMetadata,
    ) -> None:
        """
        Salvează rezultatele transcrierii: segmente + metadata finală.

        Trei operații în ACEEAȘI tranzacție:
            1. INSERT bulk segmente (executemany)
            2. UPDATE transcripts → completed
            3. UPDATE recordings → completed

        Dacă oricare eșuează → tot se rollback → jobul poate fi reînceput.

        executemany() vs execute() individual:
            300 segmente × execute() = 300 round-trips la DB (~300ms)
            300 segmente × executemany() = 1 batch (~5ms)
            → de ~60x mai rapid!

        IMPORTANT: executemany() acceptă EXCLUSIV liste de tuple-uri.
        asyncpg NU acceptă dict-uri ca în MySQL/SQLite.
        Ordinea valorilor trebuie să corespundă cu $1, $2, $3...
        """
        # Construim lista de tuple-uri pentru bulk insert
        # Ordinea: (id, transcript_id, segment_index, start, end, text, confidence, language)
        segment_tuples = [
            (
                str(uuid.uuid4()),   # $1 — UUID nou pentru fiecare segment
                transcript_id,       # $2
                seg.segment_index,   # $3
                seg.start_time,      # $4 — DECIMAL(10,3) în DB
                seg.end_time,        # $5
                seg.text,            # $6 — TEXT
                seg.confidence,      # $7 — DECIMAL(4,3): 0.000 - 1.000
                seg.language,        # $8 — VARCHAR(10): "ro", "en"
            )
            for seg in segments
        ]

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # ── 1. Bulk insert segmente ───────────────────────────
                # ON CONFLICT DO NOTHING = idempotent:
                # Dacă workerul e omorât și restartat la mijloc,
                # a doua încercare nu va crăpa pe UNIQUE (transcript_id, segment_index).
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
                # NOTĂ: trigger-ul DB 'update_search_vector_on_segment'
                # se execută automat după fiecare INSERT în transcript_segments.
                # Nu trebuie să actualizăm search_vector manual!

                # ── 2. Actualizăm transcriptul ────────────────────────
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
                    metadata.confidence_avg,
                    metadata.processing_time_sec,
                    metadata.language,
                )

                # ── 3. Actualizăm înregistrarea ───────────────────────
                await conn.execute(
                    """
                    UPDATE recordings
                    SET status = 'completed',
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                    recording_id,
                )

        logger.info(
            "results_saved",
            transcript_id=transcript_id,
            segments_count=len(segments),
            word_count=metadata.word_count,
            language=metadata.language,
        )

    async def mark_failed(
        self,
        transcript_id: str,
        recording_id: str,
        error_message: str,
    ) -> None:
        """
        Marchează jobul ca eșuat cu mesajul de eroare.

        Apelat din consumer.py în blocul except:
            try:
                await _process_job(job)
            except Exception as e:
                await uploader.mark_failed(..., str(e))
                # workerul continuă cu următorul job!

        De ce salvăm error_message în DB?
        Administratorul poate vedea exact ce a eșuat fără
        să caute prin loguri. Util pentru debug și support.
        """
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
            error=error_message[:200],  # trunchiiem pentru log
        )
