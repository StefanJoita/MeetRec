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
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.middleware.auth import get_current_user
from src.models.audit_log import User
from src.schemas.recording import SearchResponse, SemanticSearchResponse, CombinedSearchResponse
from src.services.search_service import SearchService
from src.middleware.audit import log_audit

router = APIRouter(prefix="/search", tags=["search"], dependencies=[Depends(get_current_user)])
limiter = Limiter(key_func=get_remote_address)


@router.get(
    "/",
    response_model=SearchResponse,
    summary="Caută în transcrieri",
)
@limiter.limit("60/minute")
async def search_transcripts(
    request: Request,
    q: str = Query(min_length=2, description="Termenul de căutare"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    language: Optional[str] = Query(default=None, description="'ro' sau 'en'"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Caută în toate transcripturile completate.
    Participanții văd doar înregistrările la care au acces.
    """
    start = time.time()

    service = SearchService(db)
    results, total = await service.search(
        query=q,
        limit=limit,
        offset=offset,
        language=language,
        current_user=current_user,
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


@router.get(
    "/semantic",
    response_model=SemanticSearchResponse,
    summary="Căutare semantică în transcrieri",
)
@limiter.limit("30/minute")
async def semantic_search_transcripts(
    request: Request,
    q: str = Query(min_length=2, description="Întrebare sau frază în limbaj natural"),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    start = time.time()

    service = SearchService(db)
    results, total = await service.semantic_search(query=q, limit=limit, current_user=current_user)

    elapsed_ms = int((time.time() - start) * 1000)

    await log_audit(
        request, db, action="SEMANTIC_SEARCH",
        details={"query": q, "total": total, "ms": elapsed_ms}
    )

    return SemanticSearchResponse(
        query=q,
        results=results,
        total_results=total,
        limit=limit,
        search_time_ms=elapsed_ms,
    )


@router.get(
    "/combined",
    response_model=CombinedSearchResponse,
    summary="Căutare combinată FTS + semantic",
)
async def combined_search_transcripts(
    request: Request,
    q: str = Query(min_length=2, description="Termen sau frază de căutat"),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    start = time.time()

    service = SearchService(db)
    results, stats = await service.combined_search(query=q, limit=limit, current_user=current_user)

    elapsed_ms = int((time.time() - start) * 1000)

    await log_audit(
        request, db, action="SEARCH",
        details={"query": q, "mode": "combined", "total": len(results), "ms": elapsed_ms, **stats}
    )

    return CombinedSearchResponse(
        query=q,
        results=results,
        total_results=len(results),
        fts_count=stats["fts_count"],
        semantic_count=stats["semantic_count"],
        both_count=stats["both_count"],
        search_time_ms=elapsed_ms,
    )