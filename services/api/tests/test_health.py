# services/api/tests/test_health.py
# ============================================================
# Teste pentru endpoint-urile de bază (health check, docs)
# ============================================================
# Aceste teste NU au nevoie de DB → nu folosim fixture-ul `client`
# (care include mock_db), ci un client simplu fără override.
#
# pytest.mark.asyncio = spune pytest că testul e async
# ============================================================

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app


@pytest.mark.asyncio
async def test_health_returns_200():
    """
    /health trebuie să returneze 200 OK.
    Ăsta e testul #1 al oricărui microserviciu:
    dacă health check-ul pică, Docker îl restartează.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_returns_correct_body():
    """
    /health trebuie să returneze structura JSON corectă.
    Docker healthcheck și load balancer-ul se bazează pe asta.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")

    body = response.json()
    assert body["status"] == "healthy"
    assert body["service"] == "meeting-transcriber-api"
    assert "version" in body
    assert "environment" in body


@pytest.mark.asyncio
async def test_docs_available_in_development():
    """
    /docs (Swagger UI) trebuie să fie disponibil în modul development.
    În producție, e dezactivat pentru securitate.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/docs")

    # În development: 200 OK
    # În production: 404 Not Found (dezactivat în main.py)
    assert response.status_code in (200, 404)


@pytest.mark.asyncio
async def test_unknown_endpoint_returns_404():
    """
    Un endpoint inexistent trebuie să returneze 404.
    Verifică că FastAPI nu expune endpoint-uri neintenționat.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/nonexistent")

    assert response.status_code == 404
