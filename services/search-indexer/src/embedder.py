# services/search-indexer/src/embedder.py
# ============================================================
# Embedder — generează vectori semantici cu sentence-transformers
# ============================================================
# sentence-transformers este sincron (PyTorch sub capotă).
# Rulăm în thread pool cu run_in_executor pentru a nu bloca asyncio.
#
# Modelul ales: paraphrase-multilingual-MiniLM-L12-v2
#   - 384 dimensiuni (pgvector vector(384))
#   - Antrenat pe 50+ limbi inclusiv română
#   - ~120MB, rapid pe CPU (~50ms/segment)
#   - normalize_embeddings=True → vectori unitari → cosine = dot product

import asyncio
from typing import List

import structlog

from src.config import settings

logger = structlog.get_logger(__name__)


class Embedder:

    def __init__(self):
        self._model = None

    async def load_model(self) -> None:
        """
        Încarcă modelul din cache (sau descarcă prima oară).
        Modelul e stocat în volumul Docker /app/models (persistent).
        Prima descărcare: ~120MB. Ulterior: instant din cache.
        """
        loop = asyncio.get_running_loop()
        logger.info("loading_embedding_model", model=settings.embedding_model)

        # sentence-transformers.load e sincron și durează 2-5s
        # → run_in_executor pentru a nu bloca event loop-ul
        from sentence_transformers import SentenceTransformer

        self._model = await loop.run_in_executor(
            None,
            lambda: SentenceTransformer(
                settings.embedding_model,
                cache_folder=str(settings.embedding_model_path),
            ),
        )
        logger.info("embedding_model_loaded", model=settings.embedding_model)

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Generează embeddings pentru o listă de texte.
        Returnează liste de float-uri (384 valori per text).

        normalize_embeddings=True → vectori unitari (magnitudine=1)
        → distanța cosinus = simplu dot product → mai rapid în pgvector
        """
        if not texts:
            return []

        loop = asyncio.get_running_loop()
        embeddings = await loop.run_in_executor(
            None,
            lambda: self._model.encode(
                texts,
                normalize_embeddings=True,
                batch_size=settings.embedding_batch_size,
                show_progress_bar=False,
            ),
        )
        return [emb.tolist() for emb in embeddings]

    async def embed_one(self, text: str) -> List[float]:
        """Shortcut pentru un singur text."""
        results = await self.embed([text])
        return results[0]
