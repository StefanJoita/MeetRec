# services/api/tests/test_admin_settings.py
# ============================================================
# Administrare → Setări / Stare sistem
# ============================================================
# Stocarea (tabelul app_settings) e înlocuită cu un dict în memorie;
# validarea, consistența și scrierea în DB au teste separate mai jos.
# ============================================================

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.main import app
from src.middleware.auth import get_current_user
from src.models.audit_log import User
from src.routers import admin as admin_router
from src.services import app_settings as registry


def make_user(is_admin: bool) -> MagicMock:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.username = "admin" if is_admin else "operator1"
    user.is_active = True
    user.is_admin = is_admin
    user.is_participant = False
    user.must_change_password = False
    return user


@pytest.fixture
def store(monkeypatch):
    """app_settings în memorie: {cheie: rând}."""
    rows = {}

    async def overrides(db):
        return dict(rows)

    async def effective_value(db, key):
        row = rows.get(key)
        return row.value if row else registry.env_value(registry.BY_KEY[key])

    async def set_value(db, key, value, user_id):
        d = registry.BY_KEY[key]
        value = registry.validate(d, value)
        values = {s.key: registry.effective(s, rows) for s in registry.SETTINGS}
        values[key] = value
        registry.check_consistency(values)
        rows[key] = SimpleNamespace(key=key, value=value, updated_by=None,
                                    updated_at=datetime.now(timezone.utc))
        return value

    async def reset_value(db, key):
        rows.pop(key, None)

    monkeypatch.setattr(registry, "overrides", overrides)
    monkeypatch.setattr(registry, "effective_value", effective_value)
    monkeypatch.setattr(registry, "set_value", set_value)
    monkeypatch.setattr(registry, "reset_value", reset_value)
    return rows


@pytest.fixture
def audit(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(admin_router, "log_audit", mock)
    return mock


@pytest_asyncio.fixture
async def http():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def login(user):
    db = AsyncMock(spec=AsyncSession)

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db
    return db


def by_key(items):
    return {i["key"]: i for i in items}


# ── API ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_shows_env_values_by_default(http, store, monkeypatch):
    monkeypatch.setenv("MAX_JOB_ATTEMPTS", "3")
    login(make_user(is_admin=True))

    resp = await http.get("/api/v1/admin/settings")

    assert resp.status_code == 200
    item = by_key(resp.json())["max_job_attempts"]
    assert item["value"] == 3 and item["source"] == "env"
    assert {i["key"] for i in resp.json()} == set(registry.BY_KEY)


@pytest.mark.asyncio
async def test_update_overrides_value_and_is_audited(http, store, audit, monkeypatch):
    monkeypatch.setenv("RETENTION_DAYS", "1095")
    db = login(make_user(is_admin=True))

    resp = await http.put("/api/v1/admin/settings/retention_days", json={"value": 730})

    assert resp.status_code == 200
    item = by_key(resp.json())["retention_days"]
    assert item["value"] == 730 and item["source"] == "interfata" and item["env_value"] == 1095
    audit.assert_awaited_once()
    assert audit.call_args.kwargs["details"] == {"key": "retention_days", "old": 1095, "new": 730}
    db.commit.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("key, value, message", [
    ("retention_days", 5, "minimă este 30"),
    ("max_file_size_mb", 2000, "maximă este 600"),
    ("diarization_enabled", "da", "adevărat sau fals"),
    ("max_job_attempts", None, "obligatorie"),
    ("classification_level", "   ", "obligatorie"),
    ("classification_level", "S" * 101, "Maximum 100"),
    ("classification_level", 5, "un text"),
])
async def test_invalid_values_rejected(http, store, audit, key, value, message):
    login(make_user(is_admin=True))

    resp = await http.put(f"/api/v1/admin/settings/{key}", json={"value": value})

    assert resp.status_code == 422
    assert message in resp.json()["detail"]
    assert store == {}
    audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_min_speakers_cannot_exceed_max(http, store, audit):
    login(make_user(is_admin=True))
    await http.put("/api/v1/admin/settings/max_speakers", json={"value": 3})

    resp = await http.put("/api/v1/admin/settings/min_speakers", json={"value": 5})

    assert resp.status_code == 422
    assert "minim de vorbitori" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_reset_returns_to_env(http, store, audit, monkeypatch):
    monkeypatch.setenv("STUCK_TRANSCRIPTION_HOURS", "6")
    login(make_user(is_admin=True))
    await http.put("/api/v1/admin/settings/stuck_transcription_hours", json={"value": 12})

    resp = await http.delete("/api/v1/admin/settings/stuck_transcription_hours")

    item = by_key(resp.json())["stuck_transcription_hours"]
    assert item["value"] == 6 and item["source"] == "env"
    assert audit.call_args.kwargs["details"]["reset"] is True


@pytest.mark.asyncio
async def test_unknown_setting_404(http, store, audit):
    login(make_user(is_admin=True))

    resp = await http.put("/api/v1/admin/settings/jwt_secret_key", json={"value": "x"})

    assert resp.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("method, path", [
    ("get", "/api/v1/admin/settings"),
    ("put", "/api/v1/admin/settings/retention_days"),
    ("delete", "/api/v1/admin/settings/retention_days"),
    ("get", "/api/v1/admin/system"),
])
async def test_non_admin_forbidden(http, store, method, path):
    login(make_user(is_admin=False))

    kwargs = {"json": {"value": 100}} if method == "put" else {}
    resp = await getattr(http, method)(path, **kwargs)

    assert resp.status_code == 403
    assert store == {}


@pytest.mark.asyncio
async def test_upload_config_for_any_user(http, store):
    login(make_user(is_admin=False))
    store["max_file_size_mb"] = SimpleNamespace(value=200, updated_by=None, updated_at=None)

    resp = await http.get("/api/v1/config/upload")

    assert resp.json() == {"max_file_size_bytes": 200 * 1024 * 1024}


@pytest.mark.asyncio
async def test_classification_is_public_and_defaults_to_neclasificat(http, store, monkeypatch):
    monkeypatch.delenv("CLASSIFICATION_LEVEL", raising=False)
    db = AsyncMock(spec=AsyncSession)

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db     # fără utilizator: apare și la autentificare

    resp = await http.get("/api/v1/config/classification")

    assert resp.status_code == 200
    assert resp.json() == {"level": "NECLASIFICAT"}


@pytest.mark.asyncio
async def test_classification_set_from_interface(http, store, audit):
    login(make_user(is_admin=True))

    resp = await http.put("/api/v1/admin/settings/classification_level",
                          json={"value": "  SECRET   DE SERVICIU "})

    assert resp.status_code == 200
    assert by_key(resp.json())["classification_level"]["value"] == "SECRET DE SERVICIU"
    assert audit.call_args.kwargs["details"]["new"] == "SECRET DE SERVICIU"
    assert (await http.get("/api/v1/config/classification")).json() == {"level": "SECRET DE SERVICIU"}


@pytest.mark.asyncio
async def test_system_status(http, store, monkeypatch):
    db = login(make_user(is_admin=True))
    counts, failed = MagicMock(), MagicMock()
    counts.all.return_value = [("completed", 7), ("failed", 1)]
    failed.all.return_value = [SimpleNamespace(id=uuid.uuid4(), title="Ședința X",
                                               error_message="OOM", updated_at=None)]
    db.execute.side_effect = [counts, failed]
    worker = {"worker_id": "stt-worker-1", "whisper_model": "large-v3-turbo"}
    monkeypatch.setattr(admin_router, "_search_index_status", AsyncMock(return_value={
        "available": True, "model": "m|ctx1", "pending_segments": 0}))
    monkeypatch.setattr(admin_router, "_redis_status", AsyncMock(return_value={
        "available": True, "queued": 2, "processing": 1, "workers": [worker]}))
    last = {"state": "ok", "trigger": "scheduled", "finished_at": "2026-10-29T02:01:00", "db_bytes": 1024}
    monkeypatch.setattr(admin_router, "_backup_status", AsyncMock(return_value={
        "enabled": None, "path": "/opt/meetrec-backups", "last": last, "requested": False}))
    monkeypatch.setenv("MEETREC_VERSION", "1.0.0")

    resp = await http.get("/api/v1/admin/system")

    body = resp.json()
    assert resp.status_code == 200
    assert body["version"] == "1.0.0"
    assert body["recordings_by_status"] == {"completed": 7, "failed": 1}
    assert body["queue"]["workers"] == [worker]
    assert body["recent_failures"][0]["title"] == "Ședința X"
    assert body["backup"] == {"enabled": True, "path": "/opt/meetrec-backups", "last": last, "requested": False}


# ── Backup la cerere ─────────────────────────────────────────

@pytest.fixture
def fake_redis(monkeypatch):
    import fakeredis.aioredis
    server = fakeredis.FakeServer()
    monkeypatch.setattr(admin_router.aioredis, "from_url",
                        lambda *a, **k: fakeredis.aioredis.FakeRedis(server=server, decode_responses=True))
    return fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)


@pytest.mark.asyncio
async def test_backup_run_queues_request_and_is_audited(http, audit, fake_redis):
    login(make_user(is_admin=True))

    resp = await http.post("/api/v1/admin/backup/run")

    assert resp.status_code == 202
    assert json.loads(await fake_redis.get(admin_router.BACKUP_REQUEST_KEY)) == {"by": "admin"}
    assert audit.call_args.kwargs["resource_type"] == "backup"
    assert audit.call_args.kwargs["details"] == {"event": "backup_requested"}


@pytest.mark.asyncio
async def test_backup_run_refused_while_running(http, audit, fake_redis):
    login(make_user(is_admin=True))
    await fake_redis.set(admin_router.BACKUP_STATUS_KEY, json.dumps({"state": "running"}))

    resp = await http.post("/api/v1/admin/backup/run")

    assert resp.status_code == 409
    assert not await fake_redis.exists(admin_router.BACKUP_REQUEST_KEY)
    audit.assert_not_called()


@pytest.mark.asyncio
async def test_backup_run_admin_only(http, audit, fake_redis):
    login(make_user(is_admin=False))

    resp = await http.post("/api/v1/admin/backup/run")

    assert resp.status_code == 403
    assert not await fake_redis.exists(admin_router.BACKUP_REQUEST_KEY)


@pytest.mark.asyncio
async def test_backup_status_reads_redis(fake_redis, monkeypatch):
    monkeypatch.setenv("BACKUP_HOST_PATH", "/mnt/backup")
    await fake_redis.set(admin_router.BACKUP_STATUS_KEY, json.dumps({"state": "failed", "error": "disc plin"}))

    status = await admin_router._backup_status()

    assert status["path"] == "/mnt/backup"
    assert status["last"] == {"state": "failed", "error": "disc plin"}
    assert status["requested"] is False


# ── Registrul de setări ──────────────────────────────────────

class TestRegistry:

    def test_env_value_parsing(self, monkeypatch):
        d = registry.BY_KEY
        monkeypatch.setenv("DIARIZATION_ENABLED", "true")
        monkeypatch.setenv("MIN_SPEAKERS", "")
        monkeypatch.setenv("MAX_FILE_SIZE_BYTES", str(300 * 1024 * 1024))
        monkeypatch.setenv("MAX_JOB_ATTEMPTS", "nu-e-numar")

        assert registry.env_value(d["diarization_enabled"]) is True
        assert registry.env_value(d["min_speakers"]) is None
        assert registry.env_value(d["max_file_size_mb"]) == 300
        assert registry.env_value(d["max_job_attempts"]) == 2      # invalid → implicit

    def test_optional_int_accepts_null(self):
        assert registry.validate(registry.BY_KEY["max_speakers"], None) is None

    def test_bool_is_not_accepted_as_int(self):
        with pytest.raises(registry.SettingValidationError):
            registry.validate(registry.BY_KEY["max_job_attempts"], True)

    @pytest.mark.asyncio
    async def test_set_value_upserts_row(self):
        db = AsyncMock(spec=AsyncSession)
        result = MagicMock()
        result.scalars.return_value.all.return_value = []        # nicio setare existentă
        db.execute.return_value = result
        user_id = uuid.uuid4()

        assert await registry.set_value(db, "abandoned_session_hours", 48, user_id) == 48

        stmt = db.execute.call_args_list[-1].args[0]
        params = stmt.compile().params
        assert params["key"] == "abandoned_session_hours" and params["value"] == 48
        assert params["updated_by"] == user_id
        assert "ON CONFLICT" in str(stmt.compile(dialect=__import__(
            "sqlalchemy.dialects.postgresql", fromlist=["dialect"]).dialect()))
