# services/api/tests/test_export.py
# ============================================================
# Teste pentru fix-ul #1: Export fără verificare RBAC
# ============================================================
# Verificăm că endpoint-ul GET /export/recording/{id}
# aplică corect check_recording_access() pentru participanți.
#
# Scenarii:
#   1. Participant fără acces → 403 Forbidden
#   2. Participant cu acces   → 200 OK (export livrat)
#   3. Admin                  → 200 OK (acces total)
#   4. Operator               → 200 OK (acces total)
# ============================================================

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.database import get_db
from src.middleware.auth import get_current_user
from src.models.audit_log import User


# ── Helpers ──────────────────────────────────────────────────

def make_user(role: str) -> MagicMock:
    """Creează un User mock cu rolul specificat."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.username = f"user_{role}"
    user.is_active = True
    user.is_admin = role == "admin"
    user.is_participant = role == "participant"
    user.must_change_password = False
    return user


def make_recording_mock(recording_id: uuid.UUID) -> MagicMock:
    rec = MagicMock()
    rec.id = recording_id
    rec.title = "Ședință test"
    rec.meeting_date = date(2024, 3, 15)
    rec.duration_formatted = "00:05:00"
    return rec


def make_transcript_mock() -> MagicMock:
    seg1 = MagicMock()
    seg1.start_time = 0.0
    seg1.text = "Bună ziua, deschidem ședința."

    transcript = MagicMock()
    transcript.status = "completed"
    transcript.language = "ro"
    transcript.word_count = 5
    transcript.segments = [seg1]
    return transcript


@pytest_asyncio.fixture
async def export_client(mock_db):
    """Client cu DB mock pentru testele de export."""
    async def _mock_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _mock_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


# ── Teste ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_export_participant_fara_acces_primeste_403(export_client, mock_db):
    """
    Un participant care NU e linkat la înregistrare
    trebuie să primească 403, nu conținutul exportului.
    """
    recording_id = uuid.uuid4()
    participant = make_user("participant")

    app.dependency_overrides[get_current_user] = lambda: participant

    with patch(
        "src.routers.export._get_transcript_and_recording",
        new_callable=AsyncMock,
        return_value=(make_recording_mock(recording_id), make_transcript_mock()),
    ), patch(
        "src.routers.export.check_recording_access",
        new_callable=AsyncMock,
        return_value=False,   # ← participant fără acces
    ), patch(
        "src.routers.export.log_audit",
        new_callable=AsyncMock,
    ):
        resp = await export_client.get(f"/api/v1/export/recording/{recording_id}?format=txt")

    assert resp.status_code == 403
    assert "interzis" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_export_participant_cu_acces_primeste_200(export_client, mock_db):
    """
    Un participant linkat explicit la înregistrare
    trebuie să poată exporta (200 + conținut txt).
    """
    recording_id = uuid.uuid4()
    participant = make_user("participant")

    app.dependency_overrides[get_current_user] = lambda: participant

    with patch(
        "src.routers.export._get_transcript_and_recording",
        new_callable=AsyncMock,
        return_value=(make_recording_mock(recording_id), make_transcript_mock()),
    ), patch(
        "src.routers.export.check_recording_access",
        new_callable=AsyncMock,
        return_value=True,    # ← participant cu acces
    ), patch(
        "src.routers.export.log_audit",
        new_callable=AsyncMock,
    ):
        resp = await export_client.get(f"/api/v1/export/recording/{recording_id}?format=txt")

    assert resp.status_code == 200
    assert b"Sedinta test" in resp.content or b"test" in resp.content.lower()


@pytest.mark.asyncio
async def test_export_admin_primeste_200_fara_check_participanti(export_client, mock_db):
    """
    Adminul are acces la orice înregistrare.
    check_recording_access returnează True direct pentru non-participanți.
    """
    recording_id = uuid.uuid4()
    admin = make_user("admin")

    app.dependency_overrides[get_current_user] = lambda: admin

    with patch(
        "src.routers.export._get_transcript_and_recording",
        new_callable=AsyncMock,
        return_value=(make_recording_mock(recording_id), make_transcript_mock()),
    ), patch(
        "src.routers.export.check_recording_access",
        new_callable=AsyncMock,
        return_value=True,
    ), patch(
        "src.routers.export.log_audit",
        new_callable=AsyncMock,
    ):
        resp = await export_client.get(f"/api/v1/export/recording/{recording_id}?format=txt")

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_export_operator_primeste_200(export_client, mock_db):
    """Operatorul are acces la toate înregistrările."""
    recording_id = uuid.uuid4()
    operator = make_user("operator")

    app.dependency_overrides[get_current_user] = lambda: operator

    with patch(
        "src.routers.export._get_transcript_and_recording",
        new_callable=AsyncMock,
        return_value=(make_recording_mock(recording_id), make_transcript_mock()),
    ), patch(
        "src.routers.export.check_recording_access",
        new_callable=AsyncMock,
        return_value=True,
    ), patch(
        "src.routers.export.log_audit",
        new_callable=AsyncMock,
    ):
        resp = await export_client.get(f"/api/v1/export/recording/{recording_id}?format=txt")

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_export_fara_autentificare_primeste_401(export_client):
    """Fără token JWT → 401."""
    recording_id = uuid.uuid4()
    # Fără override pe get_current_user → middleware-ul respinge
    resp = await export_client.get(f"/api/v1/export/recording/{recording_id}?format=txt")
    assert resp.status_code == 401
