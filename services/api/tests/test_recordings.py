# services/api/tests/test_recordings.py
# ============================================================
# Teste pentru /api/v1/recordings — CRUD complet
# ============================================================
# Strategie de test:
#   - Mockăm RecordingService (nu DB-ul direct)
#   - Motivul: testăm că router-ul face ce trebuie (coduri HTTP,
#     body JSON, etc.) — nu că SQLAlchemy funcționează
#   - SQLAlchemy + DB se testează cu teste de integrare separate
#
# Pattern:
#   Arrange: pregătim mock-ul cu date de test
#   Act:     facem request HTTP
#   Assert:  verificăm statusul și body-ul răspunsului
# ============================================================

import uuid
from datetime import date, datetime, timezone
from typing import Optional, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.database import get_db
from src.middleware.auth import get_current_user
from src.models.audit_log import User
from src.routers.recordings import get_recording_service
from src.services.recording_service import RecordingDeletionError
from src.schemas.recording import (
    PaginatedRecordings,
    RecordingListItem,
    RecordingResponse,
)


# ── User fake pentru teste ────────────────────────────────────
def make_fake_user(is_admin: bool = False) -> User:
    """Creează un User SQLAlchemy fake pentru dependency override."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.username = "test_user"
    user.is_active = True
    user.is_admin = is_admin
    return user


# ── Helper: date de test ──────────────────────────────────────

RECORDING_ID = uuid.uuid4()
MEETING_DATE = date(2024, 3, 15)
NOW = datetime(2024, 3, 15, 10, 0, tzinfo=timezone.utc)


def make_recording_response(**kwargs) -> RecordingResponse:
    """
    Creează un RecordingResponse Pydantic complet.
    Folosit ca valoare de return a mock-ului pentru serviciu.
    """
    defaults = {
        "id": RECORDING_ID,
        "title": "Ședință Consiliu Local",
        "description": "Ședință ordinară",
        "meeting_date": MEETING_DATE,
        "location": "Sala Consiliului",
        "participants": ["Ion Ionescu", "Maria Pop"],
        "original_filename": "sedinta_2024_03_15.mp3",
        "file_size_bytes": 10 * 1024 * 1024,  # 10MB
        "audio_format": "mp3",
        "duration_seconds": 3600,
        "duration_formatted": "01:00:00",
        "file_size_mb": 10.0,
        "status": "queued",
        "error_message": None,
        "created_at": NOW,
        "updated_at": NOW,
        "retain_until": None,
        "transcript": None,
    }
    defaults.update(kwargs)
    return RecordingResponse(**defaults)


def make_paginated(items: list = None, total: int = 0) -> PaginatedRecordings:
    """Creează un răspuns paginat cu items date."""
    return PaginatedRecordings(
        items=items or [],
        total=total,
        page=1,
        page_size=20,
        pages=0,
    )


# ── Fixture: mock service ──────────────────────────────────────
# Overriduim get_recording_service (nu get_db) pentru că:
#   - E mai simplu: nu trebuie să mockăm query-uri SQLAlchemy
#   - E mai precis: testăm interfața router ↔ service
#   - Separare clară: logica service-ului are propriile teste

def make_mock_service():
    """Creează un mock service cu toate metodele stubbed."""
    svc = AsyncMock()
    svc.list_recordings = AsyncMock(return_value=make_paginated())
    svc.get_by_id = AsyncMock(return_value=None)
    svc.create = AsyncMock(return_value=make_recording_response())
    svc.update = AsyncMock(return_value=None)
    svc.delete = AsyncMock(return_value=False)
    svc.process_upload = AsyncMock(return_value=MagicMock(
        recording_id=RECORDING_ID,
        title="Test",
        status="queued",
        message="Primit.",
        estimated_processing_minutes=5,
    ))
    return svc


# ── Context manager pentru dependency override ────────────────

from contextlib import asynccontextmanager


@asynccontextmanager
async def override_service(mock_svc, user: User = None):
    """
    Context manager care override-uiește dependency-urile pentru teste:
    - get_recording_service → mock service
    - get_db → mock sesiune DB (evită conexiune reală PostgreSQL)
    - get_current_user → user fake (evită validare JWT reală)
    """
    mock_db = AsyncMock()
    mock_db.add = MagicMock()

    fake_user = user or make_fake_user()

    async def _mock_db():
        yield mock_db

    app.dependency_overrides[get_recording_service] = lambda: mock_svc
    app.dependency_overrides[get_db] = _mock_db
    app.dependency_overrides[get_current_user] = lambda: fake_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


# ============================================================
# TESTE: GET /api/v1/recordings/
# ============================================================

class TestListRecordings:

    @pytest.mark.asyncio
    async def test_list_returns_200_when_empty(self):
        """Lista goală trebuie să returneze 200 (nu 404)."""
        svc = make_mock_service()
        svc.list_recordings.return_value = make_paginated(items=[], total=0)

        async with override_service(svc) as client:
            response = await client.get("/api/v1/recordings/")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_returns_paginated_structure(self):
        """
        Răspunsul trebuie să conțină structura paginată:
        items, total, page, page_size, pages.
        """
        svc = make_mock_service()
        svc.list_recordings.return_value = make_paginated(items=[], total=0)

        async with override_service(svc) as client:
            response = await client.get("/api/v1/recordings/")

        body = response.json()
        assert "items" in body
        assert "total" in body
        assert "page" in body
        assert "page_size" in body
        assert "pages" in body

    @pytest.mark.asyncio
    async def test_list_with_items(self):
        """Lista cu înregistrări trebuie să returneze datele corecte."""
        item = RecordingListItem(
            id=RECORDING_ID,
            title="Ședință test",
            meeting_date=MEETING_DATE,
            audio_format="mp3",
            duration_formatted="01:00:00",
            file_size_mb=10.0,
            status="completed",
            created_at=NOW,
            transcript_status="completed",
        )
        svc = make_mock_service()
        svc.list_recordings.return_value = make_paginated(items=[item], total=1)

        async with override_service(svc) as client:
            response = await client.get("/api/v1/recordings/")

        body = response.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["title"] == "Ședință test"

    @pytest.mark.asyncio
    async def test_list_passes_query_params_to_service(self):
        """
        Query params din URL trebuie să ajungă la service.
        Verificăm că router-ul nu ignoră parametrii.
        """
        svc = make_mock_service()
        svc.list_recordings.return_value = make_paginated()

        async with override_service(svc) as client:
            await client.get("/api/v1/recordings/?page=2&page_size=10&status=completed")

        # Verificăm că service-ul a primit parametrii corecți
        svc.list_recordings.assert_called_once_with(
            page=2,
            page_size=10,
            status_filter="completed",
            search=None,
            sort_by="created_at",
            sort_desc=True,
        )

    @pytest.mark.asyncio
    async def test_list_invalid_page_returns_422(self):
        """
        page=0 trebuie să returneze 422 (Unprocessable Entity).
        FastAPI validează automat: Query(ge=1) înseamnă 'greater or equal 1'.
        """
        svc = make_mock_service()

        async with override_service(svc) as client:
            response = await client.get("/api/v1/recordings/?page=0")

        # 422 = eroare de validare Pydantic/FastAPI
        assert response.status_code == 422


# ============================================================
# TESTE: GET /api/v1/recordings/{id}
# ============================================================

class TestGetRecording:

    @pytest.mark.asyncio
    async def test_get_existing_recording_returns_200(self):
        """O înregistrare care există trebuie să returneze 200."""
        svc = make_mock_service()
        svc.get_by_id.return_value = make_recording_response()

        async with override_service(svc) as client:
            response = await client.get(f"/api/v1/recordings/{RECORDING_ID}")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_returns_correct_data(self):
        """Datele returnate trebuie să corespundă înregistrării."""
        svc = make_mock_service()
        svc.get_by_id.return_value = make_recording_response(
            title="Ședință specială",
            status="completed",
        )

        async with override_service(svc) as client:
            response = await client.get(f"/api/v1/recordings/{RECORDING_ID}")

        body = response.json()
        assert body["title"] == "Ședință specială"
        assert body["status"] == "completed"
        # file_path NU trebuie expus (securitate!)
        assert "file_path" not in body

    @pytest.mark.asyncio
    async def test_get_nonexistent_recording_returns_404(self):
        """
        O înregistrare inexistentă trebuie să returneze 404.
        service.get_by_id returnează None → router ridică HTTPException.
        """
        svc = make_mock_service()
        svc.get_by_id.return_value = None  # ← înregistrarea nu există

        async with override_service(svc) as client:
            response = await client.get(f"/api/v1/recordings/{uuid.uuid4()}")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_invalid_uuid_returns_422(self):
        """
        Un UUID invalid în URL trebuie să returneze 422.
        FastAPI validează automat tipul parametrului de path.
        """
        svc = make_mock_service()

        async with override_service(svc) as client:
            response = await client.get("/api/v1/recordings/not-a-uuid")

        assert response.status_code == 422


# ============================================================
# TESTE: POST /api/v1/recordings/
# ============================================================

class TestCreateRecording:

    @pytest.mark.asyncio
    async def test_create_returns_201(self):
        """
        Crearea cu succes trebuie să returneze 201 Created (nu 200 OK).
        201 = "resursa a fost creată" — convenție REST.
        """
        svc = make_mock_service()

        async with override_service(svc) as client:
            response = await client.post(
                "/api/v1/recordings/",
                json={
                    "title": "Ședință Consiliu",
                    "meeting_date": "2024-03-15",
                },
            )

        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_create_calls_service_with_correct_data(self):
        """Service-ul trebuie apelat cu datele din request body."""
        svc = make_mock_service()

        async with override_service(svc) as client:
            await client.post(
                "/api/v1/recordings/",
                json={
                    "title": "Test titlu",
                    "meeting_date": "2024-01-20",
                    "location": "Sala A",
                },
            )

        # Verificăm că service.create a fost apelat
        svc.create.assert_called_once()
        # Verificăm că datele au ajuns la service
        call_args = svc.create.call_args[0][0]  # primul argument pozițional
        assert call_args.title == "Test titlu"
        assert call_args.location == "Sala A"

    @pytest.mark.asyncio
    async def test_create_title_too_short_returns_422(self):
        """
        Titlul sub 3 caractere trebuie să returneze 422.
        Pydantic validează Field(min_length=3) automat.
        """
        svc = make_mock_service()

        async with override_service(svc) as client:
            response = await client.post(
                "/api/v1/recordings/",
                json={
                    "title": "AB",   # prea scurt: min_length=3
                    "meeting_date": "2024-03-15",
                },
            )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_future_date_returns_422(self):
        """
        Data în viitor trebuie respinsă.
        Validatorul @field_validator("meeting_date") verifică asta.
        """
        svc = make_mock_service()

        async with override_service(svc) as client:
            response = await client.post(
                "/api/v1/recordings/",
                json={
                    "title": "Ședință viitoare",
                    "meeting_date": "2099-01-01",  # în viitor → invalid
                },
            )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_missing_required_field_returns_422(self):
        """
        Fără câmpuri obligatorii (title, meeting_date) → 422.
        """
        svc = make_mock_service()

        async with override_service(svc) as client:
            response = await client.post(
                "/api/v1/recordings/",
                json={"title": "Titlu"},  # lipsește meeting_date
            )

        assert response.status_code == 422


# ============================================================
# TESTE: DELETE /api/v1/recordings/{id}
# ============================================================

class TestDeleteRecording:

    @pytest.mark.asyncio
    async def test_delete_existing_returns_204(self):
        """
        Ștergerea cu succes trebuie să returneze 204 No Content.
        204 = "operația a reușit, fără body în răspuns".
        """
        svc = make_mock_service()
        svc.delete.return_value = True  # înregistrarea a existat și a fost ștearsă

        async with override_service(svc, user=make_fake_user(is_admin=True)) as client:
            response = await client.delete(f"/api/v1/recordings/{RECORDING_ID}")

        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_existing_has_no_body(self):
        """204 No Content trebuie să fie fără body."""
        svc = make_mock_service()
        svc.delete.return_value = True

        async with override_service(svc, user=make_fake_user(is_admin=True)) as client:
            response = await client.delete(f"/api/v1/recordings/{RECORDING_ID}")

        # Body gol (sau None)
        assert not response.content

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_404(self):
        """
        Ștergerea unui ID inexistent trebuie să returneze 404.
        service.delete returnează False → router ridică 404.
        """
        svc = make_mock_service()
        svc.delete.return_value = False  # înregistrarea nu există

        async with override_service(svc, user=make_fake_user(is_admin=True)) as client:
            response = await client.delete(f"/api/v1/recordings/{uuid.uuid4()}")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_returns_403_for_non_admin_user(self):
        """Operatorul nu trebuie să poată șterge înregistrări."""
        svc = make_mock_service()
        svc.delete.return_value = True

        async with override_service(svc, user=make_fake_user(is_admin=False)) as client:
            response = await client.delete(f"/api/v1/recordings/{RECORDING_ID}")

        assert response.status_code == 403
        assert response.json() == {
            "detail": "Acces interzis. Necesită drepturi de administrator."
        }

    @pytest.mark.asyncio
    async def test_delete_returns_500_when_storage_permissions_block_file_removal(self):
        """Erorile de permisiune pe storage trebuie returnate controlat, nu ca traceback brut."""
        svc = make_mock_service()
        svc.delete.side_effect = RecordingDeletionError(
            "Fișierul audio nu poate fi șters deoarece storage-ul nu permite scrierea pentru API."
        )

        async with override_service(svc, user=make_fake_user(is_admin=True)) as client:
            response = await client.delete(f"/api/v1/recordings/{RECORDING_ID}")

        assert response.status_code == 500
        assert response.json() == {
            "detail": "Fișierul audio nu poate fi șters deoarece storage-ul nu permite scrierea pentru API."
        }


# ============================================================
# TESTE: PATCH /api/v1/recordings/{id}
# ============================================================

class TestUpdateRecording:

    @pytest.mark.asyncio
    async def test_update_existing_returns_200(self):
        """PATCH pe o înregistrare existentă trebuie să returneze 200."""
        svc = make_mock_service()
        svc.update.return_value = make_recording_response(title="Titlu nou")

        async with override_service(svc) as client:
            response = await client.patch(
                f"/api/v1/recordings/{RECORDING_ID}",
                json={"title": "Titlu nou"},
            )

        assert response.status_code == 200
        assert response.json()["title"] == "Titlu nou"

    @pytest.mark.asyncio
    async def test_update_nonexistent_returns_404(self):
        """PATCH pe ID inexistent → 404."""
        svc = make_mock_service()
        svc.update.return_value = None  # service returnează None dacă nu există

        async with override_service(svc) as client:
            response = await client.patch(
                f"/api/v1/recordings/{uuid.uuid4()}",
                json={"title": "Titlu"},
            )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_partial_fields_only(self):
        """
        PATCH semantic: trimiți DOAR câmpurile de actualizat.
        Body-ul poate conține un singur câmp — e valid.
        """
        svc = make_mock_service()
        svc.update.return_value = make_recording_response(location="Sala B")

        async with override_service(svc) as client:
            response = await client.patch(
                f"/api/v1/recordings/{RECORDING_ID}",
                json={"location": "Sala B"},  # doar location, fără alte câmpuri
            )

        assert response.status_code == 200
