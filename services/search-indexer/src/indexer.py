# services/search-indexer/src/indexer.py
# ============================================================
# TranscriptIndexer — generează și salvează embeddings
# ============================================================
# Flow per transcript:
#   1. Preia segmentele fără embedding din DB
#   2. Trimite textele la Embedder în batch
#   3. Salvează vectorii în transcript_segments.embedding
#
# De ce per-segment și nu per-transcript?
#   - Căutarea semantică returnează exact fraza relevantă
#   - Permite sincronizare cu player-ul audio (start_time, end_time)
#   - Granularitate mai bună: "propun amânarea votului" → segment specific

from typing import List
import asyncpg
import structlog

from src.embedder import Embedder

logger = structlog.get_logger(__name__)


def _vector_to_pg_str(embedding: List[float]) -> str:
    """
    Convertește un vector Python în formatul string acceptat de pgvector.
    '[0.12345678, -0.23456789, ...]' → PostgreSQL îl castează cu ::vector
    """
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"


class TranscriptIndexer:

    def __init__(self, pool: asyncpg.Pool, embedder: Embedder):
        self._pool = pool
        self._embedder = embedder

    async def index_transcript(self, transcript_id: str) -> int:
        """
        Generează embeddings pentru toate segmentele unui transcript.
        Sare segmentele care au deja embedding (idempotent — safe la retry).
        Returnează numărul de segmente indexate.
        """
        # Preluăm doar segmentele fără embedding
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, text
                FROM transcript_segments
                WHERE transcript_id = $1
                  AND embedding IS NULL
                ORDER BY segment_index
                """,
                transcript_id,
            )

        if not rows:
            logger.debug("no_segments_to_index", transcript_id=transcript_id)
            return 0

        segment_ids = [str(row["id"]) for row in rows]
        texts = [row["text"] for row in rows]

        logger.info(
            "indexing_transcript",
            transcript_id=transcript_id,
            segments=len(texts),
        )

        # Generăm embeddings în batch (mai eficient decât unul câte unul)
        embeddings = await self._embedder.embed(texts)

        # Salvăm vectorii în DB
        # Folosim executemany pentru eficiență
        vector_tuples = [
            (_vector_to_pg_str(emb), seg_id)
            for emb, seg_id in zip(embeddings, segment_ids)
        ]

        async with self._pool.acquire() as conn:
            await conn.executemany(
                "UPDATE transcript_segments SET embedding = $1::vector WHERE id = $2",
                vector_tuples,
            )

        logger.info(
            "transcript_indexed",
            transcript_id=transcript_id,
            segments_indexed=len(segment_ids),
        )
        return len(segment_ids)
