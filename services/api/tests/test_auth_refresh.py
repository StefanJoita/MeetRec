# services/api/tests/test_auth_refresh.py
# ============================================================
# POST /auth/refresh — token nou pentru utilizatorul autentificat
# (înregistrarea din browser îl reînnoiește pe parcursul ședinței)
# ============================================================

import uuid
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.middleware.auth import decode_token, get_current_user
from src.models.audit_log import User


@pytest_asyncio.fixture
async def http():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_refresh_returns_new_token_for_current_user(http):
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    app.dependency_overrides[get_current_user] = lambda: user

    resp = await http.post("/api/v1/auth/refresh", headers={"Authorization": "Bearer x"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    assert decode_token(body["access_token"]) == str(user.id)


@pytest.mark.asyncio
async def test_refresh_requires_authentication(http):
    resp = await http.post("/api/v1/auth/refresh")
    assert resp.status_code == 401
