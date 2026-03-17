# services/api/tests/conftest.py
# ============================================================
# Configurare globală pentru pytest
# ============================================================
# conftest.py este fișierul "magic" al pytest:
#   - e încărcat automat înaintea oricărui test
#   - fixture-urile definite aici sunt disponibile în TOATE testele
#   - nu trebuie importat manual
#
# Ce facem aici:
#   1. Definim fixture-ul `app` cu dependency overrides (DB mock)
#   2. Definim fixture-ul `client` = httpx.AsyncClient
#   3. Definim fixture-ul `mock_db` = sesiune DB simulată
# ============================================================

import os
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

# ── Variabile de mediu pentru teste ──────────────────────────
# Settings() e instanțiat la import-time (module level în config.py).
# Dacă DATABASE_URL și JWT_SECRET_KEY lipsesc → ValidationError la import.
# Soluție: setăm valorile ÎNAINTE de "from src.main import app".
#
# os.environ.setdefault = setează DOAR dacă nu există deja
# (util dacă rulezi testele cu un .env real)
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test_user:test_pass@localhost:5432/test_db",
)
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test_secret_key_for_testing_only_32ch",
)

from src.main import app
from src.database import get_db


# ── Fixture: mock_db ─────────────────────────────────────
# Un "mock" este un obiect fals care simulează comportamentul unui obiect real.
# Avantaje:
#   - Testele rulează fără PostgreSQL pornit
#   - Testele sunt rapide (fără I/O real)
#   - Putem controla exact ce returnează DB-ul
#
# AsyncMock = versiunea async a MagicMock
# (necesară pentru funcții async: await db.execute(...))

@pytest.fixture
def mock_db() -> AsyncMock:
    """
    Returnează o sesiune DB simulată.
    Toate metodele async (execute, commit, rollback) sunt stubbed.
    """
    db = AsyncMock(spec=AsyncSession)
    return db


# ── Fixture: app cu DB override ───────────────────────────
# FastAPI Dependency Override:
#   app.dependency_overrides[get_db] = lambda: mock_db
#
# Asta înseamnă: "ori de câte ori cineva cere get_db,
# dă-le mock_db în schimb"
#
# E ca un test double în TDD: înlocuim dependența reală
# cu una controlată.

@pytest.fixture
def override_db(mock_db):
    """
    Override-uiește get_db cu mock-ul.
    Folosit în fixture-ul `client`.
    """
    async def _mock_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _mock_get_db
    yield mock_db
    # Cleanup: restaurăm override-urile după test
    app.dependency_overrides.clear()


# ── Fixture: client HTTP ──────────────────────────────────
# httpx.AsyncClient cu ASGITransport:
#   - Nu face request-uri reale la localhost
#   - Trimite request-urile direct în memory către FastAPI
#   - Util pentru teste: nu necesită server pornit
#
# pytest_asyncio.fixture = fixture async (pentru await)

@pytest_asyncio.fixture
async def client(override_db) -> AsyncGenerator[AsyncClient, None]:
    """
    Client HTTP async pentru testarea endpoint-urilor.
    Folosește DB mock (fără PostgreSQL real).
    """
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ── Fixture: client fără auth (pentru teste 401) ─────────
@pytest_asyncio.fixture
async def client_no_auth() -> AsyncGenerator[AsyncClient, None]:
    """
    Client fără dependency overrides — pentru teste de autentificare.
    DB-ul va eșua (nu e conectat), dar 401 vine înainte de DB.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ── Helper: date de test ──────────────────────────────────

def make_recording_dict(
    id: str = None,
    title: str = "Ședință Consiliu Local",
    status: str = "queued",
) -> dict:
    """Returnează un dict care simulează o înregistrare din DB."""
    return {
        "id": id or str(uuid.uuid4()),
        "title": title,
        "description": "Ședință ordinară lunară",
        "meeting_date": datetime(2024, 3, 15, 10, 0, tzinfo=timezone.utc),
        "status": status,
        "file_path": "/data/processed/2024/03/15/test.mp3",
        "audio_format": "mp3",
        "file_size_bytes": 10 * 1024 * 1024,
        "duration_seconds": 3600.0,
        "sha256_hash": "abc123",
        "created_at": datetime(2024, 3, 15, 10, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2024, 3, 15, 10, 0, tzinfo=timezone.utc),
    }
