# services/search-indexer/src/indexer.py
# ============================================================
# TranscriptIndexer — generează și salvează embeddings
# ============================================================
# Flow per transcript:
#   1. Preia segmentele transcrierii (toate — vecinii dau contextul)
#   2. Alege segmentele fără vector sau cu vector de la alt model / alt context
#   3. Trimite textele (cu context) la Embedder în batch
#   4. Salvează vectorii și semnătura modelului în transcript_segments
#
# De ce per-segment și nu per-transcript?
#   - Căutarea semantică returnează exact fraza relevantă
#   - Permite sincronizare cu player-ul audio (start_time, end_time)
#   - Granularitate mai bună: "propun amânarea votului" → segment specific

import asyncio
from typing import List, Sequence

import asyncpg
import structlog

from src.config import settings
from src.embedder import Embedder

logger = structlog.get_logger(__name__)


def _vector_to_pg_str(embedding: List[float]) -> str:
    """
    Convertește un vector Python în formatul string acceptat de pgvector.
    '[0.12345678, -0.23456789, ...]' → PostgreSQL îl castează cu ::vector
    """
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"


def with_context(texts: Sequence[str], index: int, context: int) -> str:
    """Textul segmentului `index` împreună cu `context` segmente vecine de fiecare parte."""
    lo, hi = max(0, index - context), min(len(texts), index + context + 1)
    return " ".join(texts[lo:hi])


class TranscriptIndexer:

    def __init__(self, pool: asyncpg.Pool, embedder: Embedder):
        self._pool = pool
        self._embedder = embedder
        # Notificările și verificarea periodică pot cere aceeași transcriere simultan;
        # modelul folosește oricum tot CPU-ul → indexăm pe rând.
        self._lock = asyncio.Lock()

    async def index_transcript(self, transcript_id: str) -> int:
        """
        Generează embeddings pentru segmentele unui transcript care nu au vector
        de la modelul curent. Idempotent — safe la retry.
        Returnează numărul de segmente indexate.
        """
        async with self._lock:
            return await self._index(transcript_id)

    async def _index(self, transcript_id: str) -> int:
        signature = settings.model_signature
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, text, (embedding IS NULL OR embedding_model IS DISTINCT FROM $2) AS stale
                FROM transcript_segments
                WHERE transcript_id = $1
                ORDER BY segment_index
                """,
                transcript_id,
                signature,
            )

        stale = [i for i, row in enumerate(rows) if row["stale"]]
        if not stale:
            logger.debug("no_segments_to_index", transcript_id=transcript_id)
            return 0

        texts = [row["text"] for row in rows]
        passages = [with_context(texts, i, settings.embedding_context_segments) for i in stale]
        logger.info("indexing_transcript", transcript_id=transcript_id, segments=len(stale))

        embeddings = await self._embedder.embed(passages)

        async with self._pool.acquire() as conn:
            await conn.executemany(
                "UPDATE transcript_segments SET embedding = $1::vector, embedding_model = $2 WHERE id = $3",
                [(_vector_to_pg_str(emb), signature, rows[i]["id"]) for emb, i in zip(embeddings, stale)],
            )

        logger.info("transcript_indexed", transcript_id=transcript_id, segments_indexed=len(stale))
        return len(stale)
