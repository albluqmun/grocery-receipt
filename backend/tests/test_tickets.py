import datetime
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.supermarket import Supermarket
from app.models.ticket import Ticket
from app.schemas.supermarket import SupermarketCreate
from app.schemas.ticket import TicketCreate
from app.services import supermarket as supermarket_service
from app.services import ticket as ticket_service

BASE = "/api/v1/tickets"


async def _create_supermarket(db: AsyncSession) -> Supermarket:
    sm = await supermarket_service.create(db, SupermarketCreate(name="Mercadona"))
    await db.commit()
    return sm


async def _create_ticket(db: AsyncSession, supermarket: Supermarket) -> Ticket:
    ticket = await ticket_service.create(
        db,
        TicketCreate(
            date=datetime.date(2026, 3, 20),
            supermarket_id=supermarket.id,
            total=Decimal("45.67"),
        ),
    )
    await db.commit()
    return ticket


async def test_list(client: AsyncClient, db_session: AsyncSession):
    sm = await _create_supermarket(db_session)
    await _create_ticket(db_session, sm)
    resp = await client.get(BASE)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


async def test_get_by_id(client: AsyncClient, db_session: AsyncSession):
    sm = await _create_supermarket(db_session)
    ticket = await _create_ticket(db_session, sm)
    resp = await client.get(f"{BASE}/{ticket.id}")
    assert resp.status_code == 200
    assert resp.json()["date"] == "2026-03-20"


async def test_get_not_found(client: AsyncClient):
    resp = await client.get(f"{BASE}/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_delete(client: AsyncClient, db_session: AsyncSession):
    sm = await _create_supermarket(db_session)
    ticket = await _create_ticket(db_session, sm)
    resp = await client.delete(f"{BASE}/{ticket.id}")
    assert resp.status_code == 204


async def test_delete_not_found(client: AsyncClient):
    resp = await client.delete(f"{BASE}/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
