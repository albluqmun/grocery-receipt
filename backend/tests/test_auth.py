import pytest
from httpx import AsyncClient

from app.core.config import Settings, settings
from app.core.security import InsecureConfigurationError, validate_security_settings


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


async def test_non_ascii_key_returns_401(api_key_enabled, client: AsyncClient):
    resp = await client.get("/api/v1/products", headers={"X-API-Key": "clavé".encode("latin-1")})
    assert resp.status_code == 401


def _settings(**kwargs) -> Settings:
    return Settings(_env_file=None, secret_key="x", **kwargs)


def test_startup_fails_without_api_key_when_not_debug():
    with pytest.raises(InsecureConfigurationError, match="API_KEY"):
        validate_security_settings(_settings(api_key="", debug=False))


def test_startup_allows_missing_key_in_debug(caplog):
    validate_security_settings(_settings(api_key="", debug=True))
    assert "API_KEY not set" in caplog.text


def test_startup_ok_with_key_and_no_debug():
    validate_security_settings(_settings(api_key="abc", debug=False))


async def test_lifespan_refuses_to_start_without_key(monkeypatch):
    from app.main import app, lifespan

    monkeypatch.setattr(settings, "api_key", "")
    monkeypatch.setattr(settings, "debug", False)
    with pytest.raises(InsecureConfigurationError):
        async with lifespan(app):
            pass
