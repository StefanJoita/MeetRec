# services/api/tests/test_inbox_session.py
# ============================================================
# Teste pentru fix-ul #2: Redis înaintea DB commit
# ============================================================
# Verificăm că /inbox/session/{id}/complete:
#   - Publică în Redis ÎNAINTE de a face commit în DB
#   - Dacă Redis pică → DB rămâne 'queued' (503 returnat)
#   - Dacă totul e OK → status devine 'transcribing' (200)
# ============================================================

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from src.main import app
from src.database import get_db
from src.middleware.auth import get_current_user
from src.models.audit_log import User
from src.models.recording import Recording


# ── Helpers ──────────────────────────────────────────────────

def make_operator() -> MagicMock:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.username = "operator1"
    user.is_active = True
    user.is_admin = False
    user.is_participant = False
    user.must_change_password = False
    return user


def make_recording_mock(session_id: uuid.UUID, status: str = "queued") -> MagicMock:
    rec = MagicMock(spec=Recording)
    rec.id = uuid.uuid4()
    rec.session_id = session_id
    rec.status = status
    rec.last_segment_at = None
    return rec


def make_db_with_recording(recording: MagicMock, extra_segments: int = 0) -> AsyncMock:
    """
    Creează un mock de DB care returnează recording-ul dat
    și un count de segmente extra specificat.
    """
    db = AsyncMock(spec=AsyncSession)

    # Prima execute → lookup recording după session_id
    # A doua execute (dacă total_segments > 1) → count segmente
    result_recording = MagicMock()
    result_recording.scalar_one_or_none.return_value = recording

    result_count = MagicMock()
    result_count.scalar_one.return_value = extra_segments

    db.execute.side_effect = [result_recording, result_count]
    return db


# ── Fixture ───────────────────────────────────────────────────

@pytest_asyncio.fixture
async def inbox_client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


# ── Teste ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_session_complete_redis_pica_db_ramane_queued(inbox_client):
    """
    Dacă Redis e indisponibil:
      - Endpoint-ul trebuie să returneze 503
      - DB trebuie să rămână în statusul 'queued' (fără commit)
    Fix verificat: Redis e apelat ÎNAINTE de db.commit().
    """
    session_id = uuid.uuid4()
    recording = make_recording_mock(session_id, status="queued")
    db = make_db_with_recording(recording, extra_segments=0)

    operator = make_operator()
    app.dependency_overrides[get_current_user] = lambda: operator
    app.dependency_overrides[get_db] = lambda: db  # sync override

    async def _db_gen():
        yield db

    app.dependency_overrides[get_db] = _db_gen

    import redis as redis_sync_module

    with patch("src.routers.inbox.redis_sync") as mock_redis_module:
        # Simulăm că Redis pică
        mock_redis_client = MagicMock()
        mock_redis_client.lpush.side_effect = redis_sync_module.RedisError("Connection refused")
        mock_redis_module.from_url.return_value = mock_redis_client
        mock_redis_module.RedisError = redis_sync_module.RedisError

        resp = await inbox_client.post(
            f"/api/v1/inbox/session/{session_id}/complete",
            data={"total_segments": "1"},
            headers={"Authorization": "Bearer fake"},  # get_current_user e override-uit
        )

    assert resp.status_code == 503
    # DB nu trebuie să fi primit commit după Redis failure
    db.commit.assert_not_called()
    # Statusul recording-ului nu trebuie modificat
    assert recording.status == "queued"


@pytest.mark.asyncio
async def test_session_complete_redis_ok_db_commit_dupa(inbox_client):
    """
    Dacă Redis e disponibil:
      - Endpoint-ul returnează 200
      - db.commit() e apelat DUPĂ lpush (nu înainte)
      - recording.status devine 'transcribing'
    """
    session_id = uuid.uuid4()
    recording = make_recording_mock(session_id, status="queued")
    db = make_db_with_recording(recording, extra_segments=0)

    operator = make_operator()
    app.dependency_overrides[get_current_user] = lambda: operator

    async def _db_gen():
        yield db

    app.dependency_overrides[get_db] = _db_gen

    # Urmărim ordinea apelurilor: Redis.lpush trebuie să vină ÎNAINTE de db.commit
    call_order = []

    import redis as redis_sync_module

    with patch("src.routers.inbox.redis_sync") as mock_redis_module:

        mock_redis_client = MagicMock()

        def track_lpush(*args, **kwargs):
            call_order.append("redis_lpush")
            return 1

        mock_redis_client.lpush.side_effect = track_lpush
        mock_redis_module.from_url.return_value = mock_redis_client
        mock_redis_module.RedisError = redis_sync_module.RedisError

        original_commit = db.commit

        async def track_commit():
            call_order.append("db_commit")

        db.commit = track_commit

        resp = await inbox_client.post(
            f"/api/v1/inbox/session/{session_id}/complete",
            data={"total_segments": "1"},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "dispatched"

    # Verificăm ordinea: Redis ÎNAINTE de DB
    assert "redis_lpush" in call_order, "lpush nu a fost apelat"
    assert "db_commit" in call_order, "commit nu a fost apelat"
    redis_idx = call_order.index("redis_lpush")
    commit_idx = call_order.index("db_commit")
    assert redis_idx < commit_idx, (
        f"DB commit ({commit_idx}) a avut loc ÎNAINTE de Redis lpush ({redis_idx})!"
    )

    # Statusul trebuie să fie transcribing după succesul complet
    assert recording.status == "transcribing"


@pytest.mark.asyncio
async def test_session_complete_inregistrare_inexistenta_404(inbox_client):
    """Dacă session_id nu există în DB → 404."""
    session_id = uuid.uuid4()
    db = AsyncMock(spec=AsyncSession)

    result = MagicMock()
    result.scalar_one_or_none.return_value = None  # nu există
    db.execute.return_value = result

    operator = make_operator()
    app.dependency_overrides[get_current_user] = lambda: operator

    async def _db_gen():
        yield db

    app.dependency_overrides[get_db] = _db_gen

    resp = await inbox_client.post(
        f"/api/v1/inbox/session/{session_id}/complete",
        data={"total_segments": "1"},
    )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_session_complete_deja_dispatchata_409(inbox_client):
    """Dacă înregistrarea are deja status 'transcribing' → 409."""
    session_id = uuid.uuid4()
    recording = make_recording_mock(session_id, status="transcribing")
    db = make_db_with_recording(recording)

    operator = make_operator()
    app.dependency_overrides[get_current_user] = lambda: operator

    async def _db_gen():
        yield db

    app.dependency_overrides[get_db] = _db_gen

    resp = await inbox_client.post(
        f"/api/v1/inbox/session/{session_id}/complete",
        data={"total_segments": "1"},
    )

    assert resp.status_code == 409
