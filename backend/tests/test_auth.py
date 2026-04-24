import pytest
from httpx import AsyncClient

from app.core.config import settings


@pytest.fixture
def api_key_enabled(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret-test-key")


async def test_missing_key_returns_401(api_key_enabled, client: AsyncClient):
    resp = await client.get("/api/v1/products")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "API key inválida o ausente"


async def test_wrong_key_returns_401(api_key_enabled, client: AsyncClient):
    resp = await client.get("/api/v1/products", headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401


async def test_correct_key_passes(api_key_enabled, client: AsyncClient):
    resp = await client.get("/api/v1/products", headers={"X-API-Key": "secret-test-key"})
    assert resp.status_code == 200


async def test_health_is_public(api_key_enabled, client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200


async def test_swagger_docs_are_public(api_key_enabled, client: AsyncClient):
    for path in ("/swagger", "/openapi.json"):
        resp = await client.get(path)
        assert resp.status_code == 200, path


async def test_disabled_when_key_empty(client: AsyncClient):
    # settings.api_key defaults to "" — middleware must no-op
    resp = await client.get("/api/v1/products")
    assert resp.status_code == 200
