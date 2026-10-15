# services/api/tests/test_recordings_activity.py
# Notificări: înregistrările în curs + cele terminate după ultima verificare;
# numele vorbitorilor: participant linkat sau nume scris liber.

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql

from src.database import get_db
from src.main import app
from src.middleware.auth import get_current_user
from src.services.recording_service import RecordingService

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


def operator():
    return SimpleNamespace(id=uuid.uuid4(), is_participant=False, is_admin=False, is_active=True,
                           must_change_password=False, role="operator")


def result(rows=(), scalar=None):
    r = MagicMock()
    r.all.return_value = list(rows)
    r.scalar_one.return_value = scalar
    return r


async def get(path, db):
    async def _db():
        yield db

    app.dependency_overrides.update({get_db: _db, get_current_user: operator})
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get(path)
    finally:
        app.dependency_overrides.clear()


def rec(status):
    return SimpleNamespace(id=uuid.uuid4(), title=f"Ședința {status}", status=status, updated_at=NOW)


@pytest.mark.asyncio
async def test_activity_returns_in_progress_and_recently_finished():
    rows = [rec("transcribing"), rec("queued"), rec("completed"), rec("failed")]
    db = AsyncMock()
    db.execute.side_effect = [result(scalar=NOW), result(rows)]

    resp = await get("/api/v1/recordings/activity?since=2026-10-15T11:59:00Z", db)

    body = resp.json()
    assert resp.status_code == 200
    assert body["server_time"] == NOW.isoformat()
    assert {r["status"] for r in body["in_progress"]} == {"transcribing", "queued"}
    assert {r["status"] for r in body["finished"]} == {"completed", "failed"}
    query = str(db.execute.call_args_list[1].args[0].compile(dialect=postgresql.dialect()))
    assert "recordings.updated_at >" in query


@pytest.mark.asyncio
async def test_first_poll_has_no_finished_items():
    db = AsyncMock()
    db.execute.side_effect = [result(scalar=NOW), result([rec("transcribing")])]

    body = (await get("/api/v1/recordings/activity", db)).json()

    assert body["finished"] == [] and len(body["in_progress"]) == 1


def test_activity_route_is_not_captured_by_recording_id():
    paths = [r.path for r in app.routes]
    assert paths.index("/api/v1/recordings/activity") < paths.index("/api/v1/recordings/{recording_id}")


# ── Numele vorbitorilor ──────────────────────────────────────

def recording_with_links(*user_ids):
    recording = SimpleNamespace(speaker_mapping={},
                                participant_links=[SimpleNamespace(user_id=u) for u in user_ids])
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=recording))
    return RecordingService(db), recording


@pytest.mark.asyncio
async def test_mapping_accepts_linked_participant_and_free_text_name():
    uid = uuid.uuid4()
    service, recording = recording_with_links(uid)

    await service.update_speaker_mapping("r", {"SPEAKER_00": str(uid), "SPEAKER_01": "  Ana Pop ",
                                               "SPEAKER_02": ""}, None)

    assert recording.speaker_mapping == {"SPEAKER_00": str(uid), "SPEAKER_01": "Ana Pop"}


@pytest.mark.asyncio
async def test_mapping_rejects_unlinked_user_id():
    service, _ = recording_with_links(uuid.uuid4())

    with pytest.raises(HTTPException) as err:
        await service.update_speaker_mapping("r", {"SPEAKER_00": str(uuid.uuid4())}, None)
    assert err.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["x" * 101, "Ion\nPopescu"])
async def test_mapping_rejects_invalid_names(name):
    service, _ = recording_with_links()

    with pytest.raises(HTTPException) as err:
        await service.update_speaker_mapping("r", {"SPEAKER_00": name}, None)
    assert err.value.status_code == 422
