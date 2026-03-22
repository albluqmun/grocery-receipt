import datetime
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.supermarket import Supermarket
from app.schemas.supermarket import SupermarketCreate
from app.schemas.ticket import TicketCreate
from app.services import supermarket as supermarket_service
from app.services import ticket as ticket_service

BASE = "/api/v1/supermarkets"


async def _create_supermarket(db: AsyncSession, **kwargs) -> Supermarket:
    defaults = {"name": "Mercadona"}
    defaults.update(kwargs)
    sm = await supermarket_service.create(db, SupermarketCreate(**defaults))
    await db.commit()
    return sm


async def test_list(client: AsyncClient, db_session: AsyncSession):
    await _create_supermarket(db_session)
    resp = await client.get(BASE)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "Mercadona"


async def test_list_pagination(client: AsyncClient, db_session: AsyncSession):
    for i in range(3):
        await _create_supermarket(db_session, name=f"Super {i}")
    resp = await client.get(BASE, params={"skip": 1, "limit": 1})
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 1


async def test_get_by_id(client: AsyncClient, db_session: AsyncSession):
    sm = await _create_supermarket(db_session, locality="Madrid")
    resp = await client.get(f"{BASE}/{sm.id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Mercadona"
    assert resp.json()["locality"] == "Madrid"


async def test_get_not_found(client: AsyncClient):
    resp = await client.get(f"{BASE}/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_delete(client: AsyncClient, db_session: AsyncSession):
    sm = await _create_supermarket(db_session)
    resp = await client.delete(f"{BASE}/{sm.id}")
    assert resp.status_code == 204
    resp = await client.get(f"{BASE}/{sm.id}")
    assert resp.status_code == 404


async def test_delete_not_found(client: AsyncClient):
    resp = await client.delete(f"{BASE}/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_delete_with_tickets(client: AsyncClient, db_session: AsyncSession):
    """Deleting a supermarket that has tickets should return 409."""
    sm = await _create_supermarket(db_session)
    await ticket_service.create(
        db_session,
        TicketCreate(date=datetime.date(2026, 3, 20), supermarket_id=sm.id, total=Decimal("10")),
    )
    await db_session.commit()
    resp = await client.delete(f"{BASE}/{sm.id}")
    assert resp.status_code == 409
