# services/search-indexer/src/http_server.py
# ============================================================
# HTTP Server — expune /embed și /reindex pentru API
# ============================================================
# Endpoint-uri:
#   GET  /health      → status serviciu + model loaded
#   POST /embed       → generează embedding pentru un text
#   POST /reindex     → declanșează re-indexare manuală (admin)
#
# Apelat de API pentru căutare semantică:
#   1. API primește GET /search/semantic?q=buget
#   2. API face POST http://search-indexer:8001/embed {"text": "buget"}
#   3. API primește {"embedding": [0.1, 0.2, ...]}
#   4. API face query pgvector cu embedding-ul

from contextlib import asynccontextmanager
from typing import List

import asyncpg
import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = structlog.get_logger(__name__)

# Referințe injectate din main.py la startup
_embedder = None
_pool: asyncpg.Pool = None
_indexer = None


def init(embedder, pool: asyncpg.Pool, indexer) -> None:
    """Injectează dependențele din main.py."""
    global _embedder, _pool, _indexer
    _embedder = embedder
    _pool = pool
    _indexer = indexer


# ── Schemas ────────────────────────────────────────────────

class EmbedRequest(BaseModel):
    text: str

class EmbedResponse(BaseModel):
    embedding: List[float]
    dimensions: int

class ReindexResponse(BaseModel):
    transcripts: int
    segments: int


# ── App ────────────────────────────────────────────────────

app = FastAPI(
    title="Search Indexer",
    description="Semantic embedding service pentru MeetRec",
    docs_url="/docs",
)


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "model_loaded": _embedder is not None and _embedder._model is not None,
    }


@app.post("/embed", response_model=EmbedResponse)
async def embed(req: EmbedRequest):
    """
    Generează embedding semantic pentru un text.
    Apelat de API pentru a transforma query-ul utilizatorului în vector.
    """
    if _embedder is None or _embedder._model is None:
        raise HTTPException(status_code=503, detail="Model not loaded yet")

    try:
        embedding = await _embedder.embed_one(req.text)
        return EmbedResponse(embedding=embedding, dimensions=len(embedding))
    except Exception as exc:
        logger.error("embed_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/reindex", response_model=ReindexResponse)
async def reindex():
    """
    Declanșează re-indexarea tuturor transcriptelor fără embeddings.
    Util după schimbarea modelului sau pentru recovery după eșecuri.
    """
    if _indexer is None:
        raise HTTPException(status_code=503, detail="Indexer not ready")

    from src.bulk_reindexer import bulk_reindex
    try:
        stats = await bulk_reindex(_pool, _indexer)
        return ReindexResponse(**stats)
    except Exception as exc:
        logger.error("reindex_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))
