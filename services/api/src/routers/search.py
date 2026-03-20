# services/api/src/routers/search.py
# ============================================================
# Full-text search în transcrieri — folosind PostgreSQL TSVECTOR
# ============================================================
# PostgreSQL full-text search 101:
#
# Indexarea (la inserare):
#   "Bună ziua, doamnelor și domnilor" 
#   → tsvector: 'bun':1 'ziua':2 'doamnelor':3 'domnilor':4
#   (cuvintele sunt stemizate: "doamnelor" → "doamn")
#
# Căutarea:
#   query: "doamne" → tsquery: 'doamn'
#   → match! (același stem)
#
# Avantaje vs LIKE '%cuvant%':
#   LIKE: scanează TOT textul, nu folosește index, lent la milioane de rânduri
#   TSVECTOR: folosește index GIN, instant chiar și la milioane de segmente
# ============================================================

import time
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.middleware.auth import get_current_user
from src.schemas.recording import SearchResponse
from src.services.search_service import SearchService
from src.middleware.audit import log_audit

router = APIRouter(prefix="/search", tags=["search"], dependencies=[Depends(get_current_user)])


@router.get(
    "/",
    response_model=SearchResponse,
    summary="Caută în transcrieri",
)
async def search_transcripts(
    request: Request,
    q: str = Query(min_length=2, description="Termenul de căutare"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    language: Optional[str] = Query(default=None, description="'ro' sau 'en'"),
    db: AsyncSession = Depends(get_db),
):
    """
    Caută în toate transcripturile completate.

    Exemple:
        GET /search?q=buget+2024
        GET /search?q=hotărâre&language=ro
        GET /search?q=vote&language=en

    Returnează segmentele care conțin termenul, cu:
    - Titlul înregistrării și data ședinței
    - Timestamp-urile (pentru sync audio)
    - Fragmentul cu termenul evidențiat
    """
    start = time.time()

    service = SearchService(db)
    results, total = await service.search(
        query=q,
        limit=limit,
        offset=offset,
        language=language,
    )

    elapsed_ms = int((time.time() - start) * 1000)

    await log_audit(
        request, db, action="SEARCH",
        details={"query": q, "total": total, "returned": len(results), "ms": elapsed_ms}
    )

    return SearchResponse(
        query=q,
        results=results,
        total_results=total,
        offset=offset,
        limit=limit,
        pages=service.pages(total, limit),
        search_time_ms=elapsed_ms,
    )