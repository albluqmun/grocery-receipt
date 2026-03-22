from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.product import Product
from app.schemas.category import CategoryCreate
from app.schemas.product import ProductCreate
from app.services import category as category_service
from app.services import product as product_service

BASE = "/api/v1/products"


async def _create_category(db: AsyncSession, **kwargs) -> Category:
    defaults = {"name": "Lácteos"}
    defaults.update(kwargs)
    cat = await category_service.create(db, CategoryCreate(**defaults))
    await db.commit()
    return cat


async def _create_product(db: AsyncSession, category: Category | None = None, **kwargs) -> Product:
    defaults = {"name": "Leche entera", "brand": "Hacendado"}
    if category:
        defaults["category_id"] = category.id
    defaults.update(kwargs)
    prod = await product_service.create(db, ProductCreate(**defaults))
    await db.commit()
    return prod


async def test_create(client: AsyncClient, db_session: AsyncSession):
    cat = await _create_category(db_session)
    resp = await client.post(BASE, json={"name": "Leche entera", "category_id": str(cat.id)})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Leche entera"
    assert data["category_id"] == str(cat.id)


async def test_create_without_category(client: AsyncClient):
    resp = await client.post(BASE, json={"name": "Producto genérico"})
    assert resp.status_code == 201
    assert resp.json()["category_id"] is None


async def test_create_invalid_category(client: AsyncClient):
    resp = await client.post(
        BASE,
        json={"name": "Producto", "category_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 409


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


async def test_update_invalid_category(client: AsyncClient, db_session: AsyncSession):
    prod = await _create_product(db_session)
    resp = await client.patch(
        f"{BASE}/{prod.id}",
        json={"category_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 409


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
