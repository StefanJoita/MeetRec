# services/api/tests/test_audit_details.py
# ============================================================
# Jurnalul de audit: numele resursei și ce s-a schimbat
# ============================================================
# Numele se salvează în details la momentul acțiunii (după ștergere
# resursa nu mai există); lista din Administrare îl afișează, cu
# descriere lizibilă, căutare după nume și filtru pe tipul resursei.
# ============================================================

import csv
import io
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql

from src.database import get_db
from src.main import app
from src.middleware.auth import get_current_admin, get_current_operator_or_above, get_current_user
from src.models.audit_log import AuditLog
from src.routers import audit as audit_router
from src.routers import recordings as recordings_router
from src.routers.recordings import get_recording_service
from src.routers.users import get_user_service
from src.services.audit_describe import describe
from tests.test_users import make_fake_admin, make_mock_service, make_user_item


def make_db():
    db = AsyncMock()
    db.add = MagicMock()
    return db


async def call(method: str, path: str, db, overrides: dict, **kwargs):
    async def _db():
        yield db

    admin = make_fake_admin()
    app.dependency_overrides.update({
        get_db: _db, get_current_admin: lambda: admin,
        get_current_operator_or_above: lambda: admin, get_current_user: lambda: admin,
        **overrides,
    })
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await getattr(client, method)(path, **kwargs)
    finally:
        app.dependency_overrides.clear()


def logged(db) -> AuditLog:
    entries = [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], AuditLog)]
    assert len(entries) == 1, entries
    return entries[0]


# ── Utilizatori ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_user_logs_name_and_role():
    db, svc = make_db(), make_mock_service()

    resp = await call("post", "/api/v1/users", db, {get_user_service: lambda: svc}, json={
        "username": "newuser", "email": "newuser@meetrec.local", "full_name": "New User",
        "password": "TempPass123"})

    assert resp.status_code == 201
    entry = logged(db)
    assert (entry.action, entry.resource_type) == ("CREATE", "user")
    assert entry.details["resource_name"] == "New User (newuser)"
    assert entry.details["role"] == "operator"


@pytest.mark.asyncio
async def test_update_user_logs_what_changed():
    db, svc = make_db(), make_mock_service()
    target = make_user_item()
    svc.get_by_id.return_value = target

    async def update(user, data, actor_user):
        user.role = "admin"
        user.is_active = False
        return user
    svc.update_user.side_effect = update

    resp = await call("patch", f"/api/v1/users/{target.id}", db, {get_user_service: lambda: svc},
                      json={"role": "admin", "is_active": False})

    assert resp.status_code == 200
    assert logged(db).details["changes"] == {"is_active": [True, False], "role": ["operator", "admin"]}


@pytest.mark.asyncio
async def test_reset_password_is_distinguishable():
    db, svc = make_db(), make_mock_service()
    target = make_user_item()
    svc.get_by_id.return_value = target

    resp = await call("post", f"/api/v1/users/{target.id}/reset-password", db,
                      {get_user_service: lambda: svc}, json={"new_password": "NouaParola123"})

    assert resp.status_code == 204
    details = logged(db).details
    assert details["event"] == "password_reset"
    assert details["resource_name"] == "New User (newuser)"


@pytest.mark.asyncio
async def test_delete_user_keeps_name_after_deletion():
    db, svc = make_db(), make_mock_service()
    target = make_user_item()
    svc.get_by_id.return_value = target

    resp = await call("delete", f"/api/v1/users/{target.id}", db, {get_user_service: lambda: svc})

    assert resp.status_code == 204
    entry = logged(db)
    assert entry.resource_id == target.id
    assert entry.details["resource_name"] == "New User (newuser)"
    assert entry.details["email"] == "newuser@meetrec.local"


# ── Înregistrări ─────────────────────────────────────────────

def make_recording(**overrides):
    values = dict(id=uuid.uuid4(), title="Ședința CA", description=None, meeting_date=date(2026, 3, 1),
                  location="Sala 1", participants=["Ion"], classification="N", speaker_mapping={})
    return SimpleNamespace(**{**values, **overrides})


@pytest.mark.asyncio
async def test_delete_recording_logs_title():
    db, svc = make_db(), AsyncMock()
    rec = make_recording()
    svc.get_by_id.return_value = rec
    svc.delete.return_value = True

    resp = await call("delete", f"/api/v1/recordings/{rec.id}", db, {get_recording_service: lambda: svc})

    assert resp.status_code == 204
    assert logged(db).details == {"resource_name": "Ședința CA"}


@pytest.mark.asyncio
async def test_update_recording_logs_title_change():
    db, svc = make_db(), AsyncMock()
    rec = make_recording()
    svc.get_by_id.return_value = rec

    async def update(recording_id, data, current_user):
        rec.title = data.title
        return rec
    svc.update.side_effect = update
    svc.to_recording_response = AsyncMock(side_effect=Exception("stop"))   # răspunsul nu contează aici

    with pytest.raises(Exception, match="stop"):
        await call("patch", f"/api/v1/recordings/{rec.id}", db, {get_recording_service: lambda: svc},
                   json={"title": "Ședința CA — martie"})

    details = logged(db).details
    assert details["resource_name"] == "Ședința CA — martie"
    assert details["changes"] == {"title": ["Ședința CA", "Ședința CA — martie"]}


@pytest.mark.asyncio
async def test_speaker_changes_use_user_names():
    ion = SimpleNamespace(id=uuid.uuid4(), username="ion", full_name="Ion Popescu")
    result = MagicMock()
    result.scalars.return_value.all.return_value = [ion]
    db = AsyncMock()
    db.execute.return_value = result

    changes = await recordings_router._speaker_changes(
        db, {"SPEAKER_00": str(ion.id), "SPEAKER_02": str(ion.id)}, {"SPEAKER_01": str(ion.id), "SPEAKER_02": str(ion.id)})

    assert changes == [
        {"speaker": "SPEAKER_00", "from": "Ion Popescu (ion)", "to": None},
        {"speaker": "SPEAKER_01", "from": None, "to": "Ion Popescu (ion)"},
    ]


# ── Descrieri ────────────────────────────────────────────────

@pytest.mark.parametrize("action, resource_type, details, expected", [
    ("UPDATE", "user", {"changes": {"role": ["operator", "admin"], "is_active": [True, False]}},
     "rol: operator → administrator; activ: da → nu"),
    ("UPDATE", "user", {"event": "password_reset"}, "parolă resetată (schimbare obligatorie la autentificare)"),
    ("UPDATE", "recording_speaker_mapping",
     {"speakers": [{"speaker": "SPEAKER_01", "from": None, "to": "Ion Popescu"}]}, "Vorbitor 2: neatribuit → Ion Popescu"),
    ("DELETE", "recording_participant", {"participant": "Ana (ana)"}, "participant eliminat: Ana (ana)"),
    ("EXPORT", "recording", {"resource_name": "X", "format": "pdf"}, "format PDF"),
    ("RETENTION_DELETE", "recording", {"title": "X", "reason": "retention_policy"}, "expirată (politica de retenție)"),
    ("RETENTION_DELETE", "audit_logs", {"deleted_count": 3, "reason": "audit_log_retention_policy"},
     "3 intrări vechi din jurnal șterse"),
    ("SEARCH", None, {"query": "buget"}, "„buget”"),
    ("VIEW", "recording", {"resource_name": "X"}, None),
])
def test_describe(action, resource_type, details, expected):
    assert describe(action, resource_type, details) == expected


# ── Lista din jurnal ─────────────────────────────────────────

def audit_row(resource_type, resource_id, details, action="DELETE"):
    log = AuditLog(id=uuid.uuid4(), timestamp=datetime(2026, 10, 15, tzinfo=timezone.utc), user_id=None,
                   user_ip="10.0.0.5", action=action, resource_type=resource_type,
                   resource_id=resource_id, details=details, success=True)
    return SimpleNamespace(AuditLog=log, user_username="admin", user_email="admin@meetrec.local")


def result(rows=(), scalar=None):
    r = MagicMock()
    r.all.return_value = list(rows)
    r.scalar_one.return_value = scalar
    return r


@pytest.mark.asyncio
async def test_list_resolves_names_and_marks_deleted():
    existing_rec, deleted_rec, old_user = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    rows = [
        audit_row("recording", deleted_rec, {"resource_name": "Ședința ștearsă"}),
        audit_row("recording", existing_rec, {}, action="VIEW"),        # intrare veche, fără nume
        audit_row("user", old_user, {}, action="UPDATE"),               # utilizator șters între timp
    ]
    db = make_db()
    db.execute.side_effect = [
        result(scalar=3),
        result(rows),
        result([(existing_rec, "Ședința CA")]),       # înregistrările care încă există
        result([]),                                   # niciun utilizator
    ]

    resp = await call("get", "/api/v1/audit-logs", db, {})

    items = resp.json()["items"]
    assert resp.status_code == 200
    assert (items[0]["resource_name"], items[0]["resource_deleted"], items[0]["recording_id"]) == \
        ("Ședința ștearsă", True, None)
    assert (items[1]["resource_name"], items[1]["resource_deleted"], items[1]["recording_id"]) == \
        ("Ședința CA", False, str(existing_rec))
    assert (items[2]["resource_name"], items[2]["resource_deleted"]) == (None, True)


def compiled(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_search_includes_resource_names():
    sql = compiled(audit_router._filtered(audit_router._rows_stmt(), "Ședința CA", None, None))

    assert "details ->> 'resource_name'" in sql
    assert "recordings.title ILIKE" in sql
    assert "users_1.full_name ILIKE" in sql


def test_resource_filter_groups_types():
    sql = compiled(audit_router._filtered(audit_router._rows_stmt(), None, None, "recording"))

    assert "'recording_speaker_mapping'" in sql and "'transcript'" in sql
    assert "'user'" not in sql


@pytest.mark.asyncio
async def test_csv_has_readable_details():
    rid = uuid.uuid4()
    db = make_db()
    db.execute.side_effect = [
        result([audit_row("user", rid, {"resource_name": "Ana (ana)", "changes": {"role": ["operator", "admin"]}},
                          action="UPDATE")]),
        result([]),
    ]

    resp = await call("get", "/api/v1/audit-logs/export?resource=user", db, {})

    text = resp.content.decode("utf-8")
    assert text.startswith("﻿")
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    assert rows[0]["resource_name"] == "Ana (ana)"
    assert rows[0]["description"] == "rol: operator → administrator"
    assert rows[0]["resource_deleted"] == "da"
    assert rows[0]["details"].startswith('{"resource_name": "Ana (ana)"')


# ── Încărcări ────────────────────────────────────────────────

@pytest.mark.parametrize("details, expected", [
    ({"resource_name": "Ședința CA", "filename": "a.mp3", "size_bytes": 5 * 1024 * 1024}, "a.mp3 · 5,0 MB"),
    ({"resource_name": "a.mp3", "filename": "a.mp3", "size_bytes": 2048}, "2 KB"),
    ({"resource_name": "X", "source": "inbox_folder", "filename": "x.wav"}, "copiat direct în folderul inbox · x.wav"),
    ({"resource_name": "X", "event": "session_started"}, "sesiune de înregistrare pornită"),
    ({"resource_name": "X", "event": "session_completed", "total_segments": 12},
     "sesiune finalizată (12 segmente), trimisă la transcriere"),
])
def test_describe_upload(details, expected):
    assert describe("UPLOAD", "recording", details) == expected


def test_describe_login():
    assert describe("LOGIN", "user", {"event": "login_success"}) == "autentificare reușită"
    assert describe("LOGIN", "user", {"event": "login_failed", "username": "x"}) == \
        "parolă greșită sau utilizator inexistent"


@pytest.mark.asyncio
async def test_upload_links_to_recording_by_hash():
    rid = uuid.uuid4()
    row = audit_row("recording", None, {"resource_name": "a.mp3", "sha256": "ff" * 32}, action="UPLOAD")
    failed_login = audit_row("user", None, {"event": "login_failed", "username": "necunoscut"}, action="LOGIN")
    db = make_db()
    db.execute.side_effect = [result(scalar=2), result([row, failed_login]),
                              result([("ff" * 32, rid, "Ședința CA")])]

    items = (await call("get", "/api/v1/audit-logs", db, {})).json()["items"]

    assert (items[0]["recording_id"], items[0]["resource_deleted"]) == (str(rid), False)
    assert (items[1]["resource_name"], items[1]["resource_deleted"]) == ("necunoscut", False)


@pytest.mark.asyncio
async def test_inbox_upload_is_audited(tmp_path, monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "inbox_path", tmp_path)
    db = make_db()
    db.execute.return_value.first = MagicMock(return_value=None)     # nu e duplicat
    db.get.return_value = None                                       # app_settings: .env

    resp = await call("post", "/api/v1/inbox/upload", db, {},
                      files={"file": ("sedinta.wav", b"RIFF1234")}, data={"title": "Ședința CA"})

    assert resp.status_code == 202
    entry = logged(db)
    assert (entry.action, entry.resource_id) == ("UPLOAD", None)
    assert entry.details["resource_name"] == "Ședința CA"
    assert entry.details["size_bytes"] == 8
    sidecar = (tmp_path / "sedinta.wav.meetrec-meta.json").read_text(encoding="utf-8")
    assert '"uploaded_via": "api"' in sidecar


@pytest.mark.asyncio
async def test_create_session_is_audited():
    db = make_db()

    resp = await call("post", "/api/v1/inbox/session/create", db, {},
                      json={"title": "Ședința CA", "meeting_date": "2026-10-15"})

    assert resp.status_code == 201
    entry = logged(db)
    assert entry.details == {"resource_name": "Ședința CA", "event": "session_started", "classification": "N"}
    assert str(entry.resource_id) == resp.json()["recording_id"]
