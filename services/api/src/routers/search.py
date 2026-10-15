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
import uuid
from datetime import date
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.limiter import limiter
from src.middleware.auth import get_current_user
from src.models.audit_log import User
from src.schemas.recording import SearchResponse, SemanticSearchResponse, CombinedSearchResponse
from src.services.search_service import SearchService
from src.middleware.audit import log_audit

router = APIRouter(prefix="/search", tags=["search"], dependencies=[Depends(get_current_user)])


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
    results, available = await service.semantic_search(query=q, limit=limit, current_user=current_user)

    elapsed_ms = int((time.time() - start) * 1000)

    await log_audit(
        request, db, action="SEMANTIC_SEARCH",
        details={"query": q, "total": len(results), "ms": elapsed_ms}
    )

    return SemanticSearchResponse(
        query=q,
        results=results,
        total_results=len(results),
        limit=limit,
        search_time_ms=elapsed_ms,
        semantic_available=available,
    )


@router.get(
    "/combined",
    response_model=CombinedSearchResponse,
    summary="Căutare combinată FTS + semantic",
)
@limiter.limit("30/minute")
async def combined_search_transcripts(
    request: Request,
    q: str = Query(min_length=2, max_length=500, description='Termeni, "frază exactă", OR, -exclus'),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50, description="Ședințe pe pagină"),
    date_from: Optional[date] = Query(default=None, description="Data minimă ședință (YYYY-MM-DD)"),
    date_to:   Optional[date] = Query(default=None, description="Data maximă ședință (YYYY-MM-DD)"),
    location:  Optional[str]  = Query(default=None, description="Filtrează după locație"),
    min_duration: Optional[int] = Query(default=None, ge=0, description="Durată minimă în secunde"),
    speaker: Optional[str] = Query(default=None, max_length=100,
                                   description="Doar fragmentele acestei persoane (id utilizator sau nume)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    start = time.time()

    service = SearchService(db)
    outcome = await service.combined_search(
        query=q, page=page, page_size=page_size, current_user=current_user,
        date_from=date_from, date_to=date_to, location=location,
        min_duration=min_duration, speaker=speaker,
    )

    elapsed_ms = int((time.time() - start) * 1000)

    # Doar prima pagină: paginarea aceleiași căutări nu e o căutare nouă
    if page == 1:
        await log_audit(
            request, db, action="SEARCH",
            details={"query": q, "mode": "combined", "total": outcome.total_hits,
                     "recordings": outcome.total_groups, "ms": elapsed_ms,
                     **({"speaker": str(speaker)} if speaker else {})},
        )

    return CombinedSearchResponse(
        query=q,
        groups=outcome.groups,
        recordings=outcome.recordings,
        total_groups=outcome.total_groups,
        total_hits=outcome.total_hits,
        page=page,
        page_size=page_size,
        pages=outcome.pages,
        fts_count=outcome.fts_count,
        semantic_count=outcome.semantic_count,
        both_count=outcome.both_count,
        semantic_available=outcome.semantic_available,
        search_time_ms=elapsed_ms,
    )


class SpeakerOption(BaseModel):
    id: str             # valoarea din speaker_mapping: id utilizator sau numele scris liber
    name: str


@router.get("/speakers", response_model=List[SpeakerOption], summary="Persoanele pentru filtrul „Vorbitor”")
async def search_speakers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Persoanele asociate cu vorbitori (Asociere vorbitori) în ședințele vizibile utilizatorului."""
    return await SearchService(db).speakers(current_user)