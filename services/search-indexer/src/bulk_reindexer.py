# services/search-indexer/src/bulk_reindexer.py
# ============================================================
# BulkReindexer — re-indexează transcriptele existente
# ============================================================
# Cazuri de utilizare:
#   1. Primul startup: transcriptele vechi nu au embeddings
#   2. Schimbare model: trebuie re-generat toți vectorii
#   3. Eșecuri parțiale: segmente rămase fără embedding
#
# Rulează la fiecare startup (safe — sare segmentele cu embedding)
# și poate fi declanșat manual prin POST /reindex

import asyncpg
import structlog

from src.indexer import TranscriptIndexer

logger = structlog.get_logger(__name__)


async def bulk_reindex(pool: asyncpg.Pool, indexer: TranscriptIndexer) -> dict:
    """
    Găsește toate transcriptele completate cu segmente fără embedding
    și le indexează pe rând.
    Returnează statistici: {transcripts, segments}.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT t.id
            FROM transcripts t
            JOIN transcript_segments seg ON seg.transcript_id = t.id
            WHERE t.status = 'completed'
              AND seg.embedding IS NULL
            ORDER BY t.id
            """
        )

    if not rows:
        logger.info("bulk_reindex_nothing_to_do")
        return {"transcripts": 0, "segments": 0}

    transcript_ids = [str(row["id"]) for row in rows]
    logger.info("bulk_reindex_started", transcripts=len(transcript_ids))

    total_segments = 0
    for tid in transcript_ids:
        count = await indexer.index_transcript(tid)
        total_segments += count

    logger.info(
        "bulk_reindex_completed",
        transcripts=len(transcript_ids),
        segments=total_segments,
    )
    return {"transcripts": len(transcript_ids), "segments": total_segments}
