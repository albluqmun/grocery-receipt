from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.product import Product, product_categories
from app.schemas.category import CategoryCreate
from app.services import category as category_service

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
    """Deleting a category with M2M products succeeds (CASCADE removes junction rows)."""
    cat = await _create_category(db_session)
    product = Product(name="Leche")
    db_session.add(product)
    await db_session.flush()
    await db_session.execute(
        product_categories.insert().values(product_id=product.id, category_id=cat.id)
    )
    await db_session.commit()
    resp = await client.delete(f"{BASE}/{cat.id}")
    assert resp.status_code == 204
