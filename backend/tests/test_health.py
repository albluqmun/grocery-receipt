import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app


@pytest.mark.asyncio
async def test_health_returns_ok():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


async def test_health_reports_degraded_when_db_unreachable(client: AsyncClient, monkeypatch):
    async def broken_execute(*args, **kwargs):
        raise ConnectionError("db down")

    monkeypatch.setattr(AsyncSession, "execute", broken_execute)

    resp = await client.get("/health")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["db"] == "disconnected"
