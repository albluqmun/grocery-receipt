from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.schemas.category import CategoryCreate
from app.schemas.product import ProductCreate
from app.services import category as category_service
from app.services import product as product_service

BASE = "/api/v1/categories"


async def _create_category(db: AsyncSession, **kwargs) -> Category:
    defaults = {"name": "Lácteos", "external_id": "dairy-001"}
    defaults.update(kwargs)
    cat = await category_service.create(db, CategoryCreate(**defaults))
    await db.commit()
    return cat


async def test_create(client: AsyncClient):
    resp = await client.post(BASE, json={"name": "Lácteos", "external_id": "dairy-001"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Lácteos"
    assert data["external_id"] == "dairy-001"


async def test_create_duplicate(client: AsyncClient, db_session: AsyncSession):
    await _create_category(db_session)
    resp = await client.post(BASE, json={"name": "Lácteos"})
    assert resp.status_code == 409


async def test_list(client: AsyncClient, db_session: AsyncSession):
    await _create_category(db_session)
    resp = await client.get(BASE)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


async def test_get_by_id(client: AsyncClient, db_session: AsyncSession):
    cat = await _create_category(db_session)
    resp = await client.get(f"{BASE}/{cat.id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Lácteos"


async def test_get_not_found(client: AsyncClient):
    resp = await client.get(f"{BASE}/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_update(client: AsyncClient, db_session: AsyncSession):
    cat = await _create_category(db_session)
    resp = await client.patch(f"{BASE}/{cat.id}", json={"name": "Carnes"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Carnes"


async def test_update_duplicate_name(client: AsyncClient, db_session: AsyncSession):
    cat = await _create_category(db_session)
    await _create_category(db_session, name="Carnes")
    resp = await client.patch(f"{BASE}/{cat.id}", json={"name": "Carnes"})
    assert resp.status_code == 409


async def test_update_not_found(client: AsyncClient):
    resp = await client.patch(f"{BASE}/00000000-0000-0000-0000-000000000000", json={"name": "X"})
    assert resp.status_code == 404


async def test_delete(client: AsyncClient, db_session: AsyncSession):
    cat = await _create_category(db_session)
    resp = await client.delete(f"{BASE}/{cat.id}")
    assert resp.status_code == 204


async def test_delete_not_found(client: AsyncClient):
    resp = await client.delete(f"{BASE}/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_delete_with_products(client: AsyncClient, db_session: AsyncSession):
    """Deleting a category that has products should return 409."""
    cat = await _create_category(db_session)
    await product_service.create(db_session, ProductCreate(name="Leche", category_id=cat.id))
    await db_session.commit()
    resp = await client.delete(f"{BASE}/{cat.id}")
    assert resp.status_code == 409
