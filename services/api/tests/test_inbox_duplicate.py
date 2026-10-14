# services/api/tests/test_inbox_duplicate.py
# ============================================================
# Fișier deja încărcat: /inbox/upload răspunde 409 cu înregistrarea existentă
# în loc de 202 (Ingest l-ar fi șters în tăcere).
# ============================================================

import hashlib
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.config import settings
from tests.test_inbox_security import http, login_as, make_user  # noqa: F401 (fixture)

AUDIO = b"RIFF....WAVEfmt continut audio"


def with_existing(db, row):
    """db.execute(...).first() → row (None = fișier nou)."""
    result = MagicMock()
    result.first.return_value = row
    db.execute.return_value = result


@pytest.mark.asyncio
async def test_duplicate_upload_returns_409_with_existing_recording(http, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "inbox_path", tmp_path)
    db = login_as(make_user(participant=False))
    existing = uuid.uuid4()
    with_existing(db, SimpleNamespace(id=existing, title="Ședința CA", meeting_date=date(2026, 10, 12)))

    resp = await http.post("/api/v1/inbox/upload", files={"file": ("copie.wav", AUDIO)})

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["recording_id"] == str(existing)
    assert detail["message"] == "Fișierul a fost deja încărcat: „Ședința CA” din 12.10.2026."
    assert list(tmp_path.iterdir()) == []          # nimic rămas în inbox pentru Ingest


@pytest.mark.asyncio
async def test_lookup_uses_sha256_of_uploaded_bytes(http, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "inbox_path", tmp_path)
    db = login_as(make_user(participant=False))
    with_existing(db, None)

    resp = await http.post("/api/v1/inbox/upload", files={"file": ("nou.wav", AUDIO)})

    assert resp.status_code == 202
    assert (tmp_path / "nou.wav").read_bytes() == AUDIO
    query = db.execute.call_args.args[0]
    assert hashlib.sha256(AUDIO).hexdigest() in query.compile().params.values()


@pytest.mark.asyncio
async def test_session_segments_skip_duplicate_check(http, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "inbox_path", tmp_path)
    db = login_as(make_user(participant=False))
    with_existing(db, None)       # lookup-ul sesiunii: încă neînregistrată

    resp = await http.post(
        "/api/v1/inbox/upload",
        files={"file": ("seg0.wav", AUDIO)},
        data={"session_id": str(uuid.uuid4()), "segment_index": "0"},
    )

    assert resp.status_code == 202
    assert db.execute.call_count == 1             # doar căutarea sesiunii, fără verificarea hash-ului
