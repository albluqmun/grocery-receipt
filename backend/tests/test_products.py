from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.schemas.product import ProductCreate
from app.services import product as product_service

BASE = "/api/v1/products"


async def _create_product(db: AsyncSession, **kwargs) -> Product:
    defaults = {"name": "Leche entera", "brand": "Hacendado"}
    defaults.update(kwargs)
    prod = await product_service.create(db, ProductCreate(**defaults))
    await db.commit()
    return prod


async def test_create(client: AsyncClient):
    resp = await client.post(BASE, json={"name": "Leche entera", "brand": "Hacendado"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Leche entera"
    assert data["brand"] == "Hacendado"
    assert data["categories"] == []


async def test_create_without_brand(client: AsyncClient):
    resp = await client.post(BASE, json={"name": "Producto genérico"})
    assert resp.status_code == 201
    assert resp.json()["brand"] is None
    assert resp.json()["categories"] == []


async def test_list(client: AsyncClient, db_session: AsyncSession):
    await _create_product(db_session)
    resp = await client.get(BASE)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


async def test_get_by_id(client: AsyncClient, db_session: AsyncSession):
    prod = await _create_product(db_session)
    resp = await client.get(f"{BASE}/{prod.id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Leche entera"


async def test_get_not_found(client: AsyncClient):
    resp = await client.get(f"{BASE}/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_update(client: AsyncClient, db_session: AsyncSession):
    prod = await _create_product(db_session)
    resp = await client.patch(f"{BASE}/{prod.id}", json={"brand": "Pascual"})
    assert resp.status_code == 200
    assert resp.json()["brand"] == "Pascual"
    assert resp.json()["name"] == "Leche entera"


async def test_update_not_found(client: AsyncClient):
    resp = await client.patch(f"{BASE}/00000000-0000-0000-0000-000000000000", json={"name": "X"})
    assert resp.status_code == 404


async def test_delete(client: AsyncClient, db_session: AsyncSession):
    prod = await _create_product(db_session)
    resp = await client.delete(f"{BASE}/{prod.id}")
    assert resp.status_code == 204


async def test_delete_not_found(client: AsyncClient):
    resp = await client.delete(f"{BASE}/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
