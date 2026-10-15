# services/api/tests/test_search.py
# ============================================================
# Căutare: interogări în limbaj natural, combinarea rezultatelor
# (Reciprocal Rank Fusion), gruparea pe ședință, filtre, jurnal.
# ============================================================

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.database import get_db
from src.main import app
from src.middleware.auth import get_current_user
from src.models.audit_log import AuditLog
from src.schemas.recording import SearchResult, SemanticSearchResult
from src.services import search_service
from src.services.search_service import SearchFilters, SearchService, any_terms_query


# ── Interogarea ──────────────────────────────────────────────

@pytest.mark.parametrize("query, expected", [
    ("proteste violente în Franța", "proteste OR violente OR Franța"),
    ("bugetul pe 2027", "bugetul OR 2027"),
    ("buget", "buget"),                                    # un singur termen: neschimbat
    ('"vot de investitură"', '"vot de investitură"'),      # sintaxa utilizatorului se respectă
    ("guvern -psd", "guvern -psd"),
    ("Franța OR Spania", "Franța OR Spania"),
    ("și de la", "și de la"),                              # doar cuvinte de legătură: neschimbat
])
def test_any_terms_query(query, expected):
    assert any_terms_query(query) == expected


def test_filters_sql_uses_dates_and_speaker():
    speaker = uuid.uuid4()
    sql, params = SearchFilters(date_from="2026-01-01", date_to=date(2026, 12, 31), speaker=speaker).sql(None)

    assert params["date_from"] == date(2026, 1, 1)         # asyncpg cere date, nu text
    assert params["date_to"] == date(2026, 12, 31)
    assert "r.speaker_mapping ->> seg.speaker_id = :speaker" in sql
    assert params["speaker"] == str(speaker)


def test_filters_without_segment_conditions_for_recordings():
    sql, params = SearchFilters(speaker=uuid.uuid4(), language="ro").sql(None, segments=False)

    assert "speaker" not in sql and "language" not in sql


def rows_result(rows):
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    return result


# ── Combinarea ───────────────────────────────────────────────

REC_A, REC_B = uuid.uuid4(), uuid.uuid4()


def fts(rec, seg, rank=0.1):
    return SearchResult(recording_id=rec, recording_title=f"Ședința {rec}"[:20], meeting_date=date(2026, 1, 1),
                        segment_id=seg, start_time=1.0, end_time=2.0, text="t", headline="<b>t</b>", rank=rank)


def sem(rec, seg, similarity=0.6):
    return SemanticSearchResult(recording_id=rec, recording_title=f"Ședința {rec}"[:20], meeting_date=date(2026, 1, 1),
                                segment_id=seg, start_time=1.0, end_time=2.0, text="t", similarity=similarity)


def service_with(fts_results, sem_results, available=True):
    svc = SearchService(AsyncMock())
    svc._get_query_embedding = AsyncMock(return_value=([0.1], "m|ctx1"))
    svc.search = AsyncMock(return_value=(fts_results, len(fts_results)))
    svc.semantic_search = AsyncMock(return_value=(sem_results, available))
    svc.recording_matches = AsyncMock(return_value=[])
    svc._resolve_speakers = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_rrf_ranks_segments_found_by_both_first():
    s1, s2, s3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    svc = service_with([fts(REC_A, s1), fts(REC_A, s2)], [sem(REC_A, s2), sem(REC_A, s3)])

    out = await svc.combined_search("buget local")

    hits = out.groups[0].hits
    assert [h.segment_id for h in hits] == [s2, s1, s3]     # s2: în ambele liste
    assert hits[0].source == "both" and hits[0].similarity == 0.6 and hits[0].rank == 0.1
    assert hits[0].score == pytest.approx(1 / 62 + 1 / 61, abs=1e-6)
    assert (out.fts_count, out.semantic_count, out.both_count) == (2, 2, 1)
    svc.search.assert_awaited_once()
    assert svc.search.call_args.kwargs["query"] == "buget OR local"


@pytest.mark.asyncio
async def test_groups_by_recording_and_paginates_groups():
    fts_results = [fts(REC_A, uuid.uuid4()) for _ in range(5)] + [fts(REC_B, uuid.uuid4())]
    svc = service_with(fts_results, [])

    page1 = await svc.combined_search("buget", page=1, page_size=1)
    page2 = await svc.combined_search("buget", page=2, page_size=1)

    assert page1.total_groups == 2 and page1.pages == 2 and page1.total_hits == 6
    assert page1.groups[0].recording_id == REC_A
    assert page1.groups[0].total_hits == 5 and len(page1.groups[0].hits) == search_service.HITS_PER_GROUP
    assert page2.groups[0].recording_id == REC_B


@pytest.mark.asyncio
async def test_semantic_unavailable_is_reported():
    svc = service_with([fts(REC_A, uuid.uuid4())], [], available=False)

    out = await svc.combined_search("buget")

    assert out.semantic_available is False
    assert out.total_hits == 1


@pytest.mark.asyncio
async def test_semantic_search_compares_only_same_model_vectors():
    db = AsyncMock()
    db.execute.return_value = rows_result([])
    svc = SearchService(db)

    results, available = await svc.semantic_search("buget", embedding=([0.5, 0.5], "model-x|ctx1"))

    assert available is True
    set_sql = str(db.execute.call_args_list[0].args[0])
    assert set_sql.startswith("SET LOCAL hnsw.ef_search")
    query, params = db.execute.call_args_list[1].args
    assert "seg.embedding_model = :model" in str(query)
    assert params["model"] == "model-x|ctx1"


@pytest.mark.asyncio
async def test_semantic_search_without_indexer():
    svc = SearchService(AsyncMock())
    svc._get_query_embedding = AsyncMock(return_value=None)

    assert await svc.semantic_search("buget") == ([], False)


@pytest.mark.asyncio
async def test_exact_search_ranks_by_segment_not_transcript():
    db = AsyncMock()
    db.scalar.return_value = 0
    db.execute.return_value = rows_result([])

    await SearchService(db).search("buget")

    sql = str(db.execute.call_args.args[0])
    assert "ts_rank_cd(seg.search_vector" in sql
    assert "t.search_vector" not in sql
    assert "websearch_to_tsquery('romanian_unaccent'" in sql


# ── Endpoint ─────────────────────────────────────────────────

async def get(path, db, user):
    async def _db():
        yield db

    app.dependency_overrides.update({get_db: _db, get_current_user: lambda: user})
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get(path)
    finally:
        app.dependency_overrides.clear()


def operator():
    return SimpleNamespace(id=uuid.uuid4(), is_participant=False, is_admin=False, is_active=True,
                           must_change_password=False, role="operator")


@pytest.mark.asyncio
async def test_combined_endpoint_audits_only_first_page():
    outcome = search_service.CombinedOutcome(groups=[], recordings=[], total_groups=0, total_hits=0,
                                             fts_count=0, semantic_count=0, both_count=0,
                                             semantic_available=True, pages=0)
    db = MagicMock(add=MagicMock(), commit=AsyncMock(), rollback=AsyncMock(), close=AsyncMock())
    with patch.object(SearchService, "combined_search", AsyncMock(return_value=outcome)) as combined:
        first = await get("/api/v1/search/combined?q=buget", db, operator())
        second = await get("/api/v1/search/combined?q=buget&page=2&speaker=" + str(uuid.uuid4()), db, operator())

    assert first.status_code == second.status_code == 200
    audits = [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], AuditLog)]
    assert len(audits) == 1 and audits[0].details["query"] == "buget"
    assert combined.call_args.kwargs["page"] == 2


@pytest.mark.asyncio
async def test_speakers_endpoint():
    uid = uuid.uuid4()
    with patch.object(SearchService, "speakers", AsyncMock(return_value=[{"id": uid, "name": "Ion Popescu"}])):
        resp = await get("/api/v1/search/speakers", AsyncMock(), operator())

    assert resp.json() == [{"id": str(uid), "name": "Ion Popescu"}]


def test_combined_search_is_rate_limited():
    from src.limiter import limiter
    assert "src.routers.search.combined_search_transcripts" in limiter._route_limits
