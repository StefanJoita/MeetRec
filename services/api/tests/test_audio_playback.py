# services/api/tests/test_audio_playback.py
# Playerul primește copia de redare (ingest/playback.py) dacă există, altfel originalul.

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.config import settings
from src.database import get_db
from src.main import app
from src.middleware.auth import create_audio_token
from src.services.recording_service import RecordingService, playback_path

RECORDING_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


def result(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "audio_storage_path", tmp_path)
    day = tmp_path / "2026/11/03"
    day.mkdir(parents=True)
    return day


@pytest_asyncio.fixture
async def http():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def serve(original):
    db = AsyncMock()
    db.execute.side_effect = [result(MagicMock(id=USER_ID)), result(MagicMock(file_path=str(original)))]

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    return f"/api/v1/recordings/{RECORDING_ID}/audio?token={create_audio_token(str(USER_ID), str(RECORDING_ID))}"


@pytest.mark.asyncio
async def test_playback_copy_is_served_when_present(http, storage):
    original = storage / "abc.mp4"
    original.write_bytes(b"video" * 100)
    playback_path(original).write_bytes(b"sunet")

    resp = await http.get(serve(original), headers={"Range": "bytes=0-"})

    assert resp.status_code == 206
    assert resp.content == b"sunet"
    assert resp.headers["content-type"] == "audio/mpeg"
    assert resp.headers["content-range"] == "bytes 0-4/5"


@pytest.mark.asyncio
async def test_original_is_served_without_copy(http, storage):
    original = storage / "abc.mp3"
    original.write_bytes(b"mp3data")

    resp = await http.get(serve(original))

    assert resp.status_code == 200
    assert resp.content == b"mp3data"
    assert resp.headers["content-type"] == "audio/mpeg"


@pytest.mark.asyncio
async def test_delete_removes_playback_copy(storage):
    original = storage / "abc.mp4"
    original.write_bytes(b"v")
    playback_path(original).write_bytes(b"a")
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())   # nicio bucată de sesiune
    svc = RecordingService(db)
    svc.get_by_id = AsyncMock(return_value=MagicMock(file_path=str(original)))

    assert await svc.delete(RECORDING_ID) is True

    assert not original.exists() and not playback_path(original).exists()


@pytest.mark.asyncio
async def test_delete_removes_session_chunk_files(storage):
    """Ștergerea unei sesiuni nelipite șterge și bucățile 1..N (BUG-01)."""
    original = storage / "s.webm"
    original.write_bytes(b"0")
    chunks = [storage / f"s_{i}.webm" for i in (1, 2)]
    for c in chunks:
        c.write_bytes(b"x")
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [str(c) for c in chunks]
    db.execute = AsyncMock(return_value=result)
    svc = RecordingService(db)
    svc.get_by_id = AsyncMock(return_value=MagicMock(file_path=str(original)))

    assert await svc.delete(RECORDING_ID) is True

    assert not original.exists() and not any(c.exists() for c in chunks)
