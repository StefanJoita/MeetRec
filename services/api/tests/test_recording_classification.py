# services/api/tests/test_recording_classification.py
# ============================================================
# Nivelul de clasificare al înregistrării (N, SSv, S, SS):
# ales la încărcare / la pornirea înregistrării din browser,
# modificabil din detaliile ședinței.
# ============================================================

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_db
from src.main import app
from src.middleware.auth import get_current_user
from src.models.audit_log import User
from src.models.recording import Recording
from src.schemas.recording import RecordingUpdate
from src.services.classification import classification_label


def make_operator() -> MagicMock:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.username = "operator1"
    user.is_active = True
    user.is_admin = False
    user.is_participant = False
    user.must_change_password = False
    return user


@pytest_asyncio.fixture
async def http():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def db():
    db = AsyncMock(spec=AsyncSession)
    db.add = MagicMock()
    db.execute.return_value.first = MagicMock(return_value=None)        # niciun fișier duplicat
    db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
    db.get.return_value = None                                          # app_settings: valorile din .env

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = make_operator
    app.dependency_overrides[get_db] = _db
    return db


def added_recording(db) -> Recording:
    [recording] = [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], Recording)]
    return recording


# ── Încărcare fișier ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_passes_classification_to_ingest(http, db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "inbox_path", tmp_path)

    resp = await http.post("/api/v1/inbox/upload", files={"file": ("a.wav", b"RIFF")},
                           data={"classification": "SSv"})

    assert resp.status_code == 202
    sidecar = json.loads((tmp_path / "a.wav.meetrec-meta.json").read_text(encoding="utf-8"))
    assert sidecar["classification"] == "SSv"


@pytest.mark.asyncio
async def test_upload_rejects_unknown_classification(http, db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "inbox_path", tmp_path)

    resp = await http.post("/api/v1/inbox/upload", files={"file": ("a.wav", b"RIFF")},
                           data={"classification": "TOP"})

    assert resp.status_code == 400
    assert "N, SSv, S, SS" in resp.json()["detail"]
    assert list(tmp_path.iterdir()) == []


# ── Înregistrare din browser ─────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("sent, stored", [("SS", "SS"), (None, "N")])
async def test_session_create_stores_classification(http, db, sent, stored):
    body = {"title": "Ședința CA", "meeting_date": "2026-10-28"}
    if sent:
        body["classification"] = sent

    resp = await http.post("/api/v1/inbox/session/create", json=body)

    assert resp.status_code == 201
    assert added_recording(db).classification == stored


@pytest.mark.asyncio
async def test_session_create_rejects_unknown_classification(http, db):
    resp = await http.post("/api/v1/inbox/session/create",
                           json={"title": "x", "meeting_date": "2026-10-28", "classification": "s"})

    assert resp.status_code == 422
    db.commit.assert_not_called()


# ── Modificare și denumiri ───────────────────────────────────

def test_update_accepts_only_known_levels():
    assert RecordingUpdate(classification="S").classification == "S"
    with pytest.raises(ValidationError):
        RecordingUpdate(classification="SECRET")


@pytest.mark.parametrize("code, label", [
    ("N", "NECLASIFICAT"), ("SSv", "SECRET DE SERVICIU"), ("S", "SECRET"), ("SS", "STRICT SECRET"),
    ("?", "NECLASIFICAT"),
])
def test_classification_label(code, label):
    assert classification_label(code) == label


@pytest.mark.asyncio
async def test_service_update_reloads_server_side_updated_at():
    """updated_at e calculat de PostgreSQL: fără reîncărcare, serializarea răspunsului dă 500."""
    from src.services.recording_service import RecordingService

    recording = MagicMock(spec=Recording)
    db = AsyncMock(spec=AsyncSession)
    db.execute.return_value.scalar_one_or_none = MagicMock(return_value=recording)

    result = await RecordingService(db).update(uuid.uuid4(), RecordingUpdate(classification="SS"))

    assert result is recording and recording.classification == "SS"
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(recording, ["updated_at"])
