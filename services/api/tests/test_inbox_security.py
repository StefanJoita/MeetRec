# services/api/tests/test_inbox_security.py
# ============================================================
# Teste de securitate pentru /inbox:
#   - participanții nu pot crea sesiuni / încărca audio (403)
#   - numele de fișier trimis de client nu poate ieși din inbox
# ============================================================

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_db
from src.main import app
from src.middleware.auth import get_current_user
from src.models.audit_log import User
from src.routers.inbox import _safe_inbox_filename


def make_user(participant: bool) -> MagicMock:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.username = "participant1" if participant else "operator1"
    user.is_active = True
    user.is_admin = False
    user.is_participant = participant
    user.must_change_password = False
    return user


@pytest_asyncio.fixture
async def http():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def login_as(user: MagicMock) -> AsyncMock:
    db = AsyncMock(spec=AsyncSession)

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db
    return db


# ── RBAC ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_participant_cannot_upload(http, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "inbox_path", tmp_path)
    login_as(make_user(participant=True))

    resp = await http.post("/api/v1/inbox/upload", files={"file": ("a.wav", b"RIFF")})

    assert resp.status_code == 403
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_participant_cannot_create_session(http):
    db = login_as(make_user(participant=True))

    resp = await http.post(
        "/api/v1/inbox/session/create",
        json={"title": "x", "meeting_date": "2026-10-09"},
    )

    assert resp.status_code == 403
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_participant_cannot_complete_session(http):
    login_as(make_user(participant=True))

    resp = await http.post(
        f"/api/v1/inbox/session/{uuid.uuid4()}/complete",
        json={"total_segments": 1},
    )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_operator_can_upload(http, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "inbox_path", tmp_path)
    login_as(make_user(participant=False))

    resp = await http.post("/api/v1/inbox/upload", files={"file": ("sedinta.wav", b"RIFF")})

    assert resp.status_code == 202
    assert (tmp_path / "sedinta.wav").read_bytes() == b"RIFF"


# ── Path traversal ───────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "evil_name, expected",
    [
        ("../processed/x.wav", "x.wav"),
        ("../../../../tmp/x.wav", "x.wav"),
        ("/app/src/evil.py", "evil.py"),
        ("..\\..\\win.wav", "win.wav"),
        ("C:\\Windows\\x.wav", "x.wav"),
    ],
)
async def test_upload_filename_cannot_escape_inbox(http, tmp_path, monkeypatch, evil_name, expected):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr(settings, "inbox_path", inbox)
    login_as(make_user(participant=False))

    resp = await http.post("/api/v1/inbox/upload", files={"file": (evil_name, b"RIFF")})

    assert resp.status_code == 202
    assert resp.json()["filename"] == expected
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written == [inbox / expected]


@pytest.mark.parametrize("bad", ["..", ".", "/", "../", "...", "   "])
def test_safe_filename_rejects_empty_or_dots(bad):
    with pytest.raises(HTTPException) as exc:
        _safe_inbox_filename(bad)
    assert exc.value.status_code == 400


def test_safe_filename_keeps_romanian_chars_and_replaces_unsafe():
    assert _safe_inbox_filename("ședință consiliu.mp3") == "ședință consiliu.mp3"
    assert _safe_inbox_filename("a:b*c?.wav") == "a_b_c_.wav"


def test_safe_filename_truncation_keeps_extension():
    name = _safe_inbox_filename("a" * 300 + ".wav")
    assert len(name) == 200 and name.endswith(".wav")
