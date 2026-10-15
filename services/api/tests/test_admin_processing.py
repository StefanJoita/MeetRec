# services/api/tests/test_admin_processing.py
# ============================================================
# Administrare → Procesări: durata transcrierii pe înregistrare
# ============================================================

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.main import app
from tests.test_admin_settings import login, make_user


@pytest_asyncio.fixture
async def http():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def row(**overrides):
    values = dict(
        id=uuid.uuid4(), title="Test YouTube", duration_seconds=222,
        completed_at=datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc),
        model_used="whisper-large-v3-turbo", processing_time_sec=276,
        transcription_sec=Decimal("154.0"), alignment_sec=Decimal("6.2"),
        diarization_sec=Decimal("264.7"), diarization_parallel=True,
    )
    return SimpleNamespace(**{**values, **overrides})


def mock_results(db, totals, rows):
    totals_result, rows_result = MagicMock(), MagicMock()
    totals_result.one.return_value = totals
    rows_result.all.return_value = rows
    db.execute.side_effect = [totals_result, rows_result]


@pytest.mark.asyncio
async def test_processing_lists_total_and_stage_durations(http):
    db = login(make_user(is_admin=True))
    mock_results(db, (1, 222, 276), [row()])

    resp = await http.get("/api/v1/admin/processing")

    assert resp.status_code == 200
    body = resp.json()
    item = body["items"][0]
    assert item["processing_sec"] == 276
    assert item["audio_sec"] == 222
    assert item["ratio"] == 1.24
    assert item["transcription_sec"] == 154.0
    assert item["diarization_sec"] == 264.7
    assert item["diarization_parallel"] is True
    assert body["summary"] == {"count": 1, "audio_sec": 222, "processing_sec": 276, "ratio": 1.24}
    assert body["pages"] == 1


@pytest.mark.asyncio
async def test_processing_without_stage_times_or_duration(http):
    """Transcrieri dinainte de migrare: fără etape; audio fără durată → fără raport."""
    db = login(make_user(is_admin=True))
    mock_results(db, (1, 0, 90), [row(duration_seconds=None, transcription_sec=None,
                                      alignment_sec=None, diarization_sec=None,
                                      diarization_parallel=False)])

    body = (await http.get("/api/v1/admin/processing")).json()

    item = body["items"][0]
    assert item["ratio"] is None
    assert item["transcription_sec"] is None
    assert item["diarization_sec"] is None
    assert body["summary"]["ratio"] is None


@pytest.mark.asyncio
async def test_processing_pagination_and_sort(http):
    db = login(make_user(is_admin=True))
    mock_results(db, (45, 0, 0), [])

    resp = await http.get("/api/v1/admin/processing?page=3&page_size=20&sort=slowest")

    assert resp.status_code == 200
    assert resp.json()["pages"] == 3
    query = str(db.execute.call_args_list[1].args[0])
    assert "ORDER BY" in query and "nullif" in query.lower()


@pytest.mark.asyncio
async def test_processing_rejects_unknown_sort(http):
    login(make_user(is_admin=True))

    resp = await http.get("/api/v1/admin/processing?sort=title")

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_processing_forbidden_for_non_admin(http):
    login(make_user(is_admin=False))

    resp = await http.get("/api/v1/admin/processing")

    assert resp.status_code == 403
