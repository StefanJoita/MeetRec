# services/search-indexer/src/bulk_reindexer.py
# ============================================================
# BulkReindexer — indexează transcriptele rămase fără vectori
# ============================================================
# Cazuri de utilizare:
#   1. Primul startup: transcriptele vechi nu au embeddings
#   2. Schimbare model / context: vectorii vechi au altă semnătură → recalculați
#   3. Notificare ratată (serviciu oprit, conexiune LISTEN căzută)
#
# Rulează la pornire și periodic (sweep_forever), sare segmentele la zi;
# poate fi declanșat și manual prin POST /reindex.

import asyncio

import asyncpg
import structlog

from src.config import settings
from src.indexer import TranscriptIndexer

logger = structlog.get_logger(__name__)

_STALE = "(seg.embedding IS NULL OR seg.embedding_model IS DISTINCT FROM $1)"


async def pending_segments(pool: asyncpg.Pool) -> int:
    """Segmentele transcrierilor finalizate care nu au vector de la modelul curent."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            f"""
            SELECT COUNT(*)
            FROM transcript_segments seg
            JOIN transcripts t ON t.id = seg.transcript_id
            WHERE t.status = 'completed' AND {_STALE}
            """,
            settings.model_signature,
        )


async def bulk_reindex(pool: asyncpg.Pool, indexer: TranscriptIndexer) -> dict:
    """
    Găsește transcriptele completate cu segmente neindexate și le indexează pe rând.
    Returnează statistici: {transcripts, segments}.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT DISTINCT t.id, t.completed_at
            FROM transcripts t
            JOIN transcript_segments seg ON seg.transcript_id = t.id
            WHERE t.status = 'completed' AND {_STALE}
            ORDER BY t.completed_at DESC NULLS LAST     -- cele mai noi întâi
            """,
            settings.model_signature,
        )

    if not rows:
        logger.debug("bulk_reindex_nothing_to_do")
        return {"transcripts": 0, "segments": 0}

    transcript_ids = [str(row["id"]) for row in rows]
    logger.info("bulk_reindex_started", transcripts=len(transcript_ids))

    total_segments = 0
    for tid in transcript_ids:
        total_segments += await indexer.index_transcript(tid)

    logger.info("bulk_reindex_completed", transcripts=len(transcript_ids), segments=total_segments)
    return {"transcripts": len(transcript_ids), "segments": total_segments}


async def sweep_forever(pool: asyncpg.Pool, indexer: TranscriptIndexer, stop: asyncio.Event) -> None:
    """bulk_reindex imediat, apoi la fiecare sweep_interval_seconds, până la `stop`."""
    while not stop.is_set():
        try:
            await bulk_reindex(pool, indexer)
        except Exception as exc:                      # DB indisponibil temporar etc.
            logger.error("sweep_failed", error=str(exc))
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.sweep_interval_seconds)
        except asyncio.TimeoutError:
            pass
