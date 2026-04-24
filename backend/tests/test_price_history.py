import uuid
from datetime import date
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.line_item import LineItem
from app.models.product import Product
from app.models.supermarket import Supermarket
from app.models.ticket import Ticket

BASE = "/api/v1/products"


async def _seed_purchase(
    db: AsyncSession,
    product: Product,
    *,
    supermarket_name: str,
    ticket_date: date,
    unit_price: Decimal,
) -> None:
    market = Supermarket(name=supermarket_name, locality="TEST")
    db.add(market)
    await db.flush()
    ticket = Ticket(date=ticket_date, supermarket_id=market.id, total=unit_price)
    db.add(ticket)
    await db.flush()
    db.add(
        LineItem(
            ticket_id=ticket.id,
            product_id=product.id,
            quantity=Decimal("1"),
            unit_price=unit_price,
            line_total=unit_price,
        )
    )
    await db.flush()


async def test_price_history_returns_entries_desc(client: AsyncClient, db_session: AsyncSession):
    prod = Product(name="Leche entera")
    db_session.add(prod)
    await db_session.flush()
    await _seed_purchase(
        db_session,
        prod,
        supermarket_name="MERCADONA",
        ticket_date=date(2026, 3, 1),
        unit_price=Decimal("1.10"),
    )
    await _seed_purchase(
        db_session,
        prod,
        supermarket_name="LIDL",
        ticket_date=date(2026, 4, 1),
        unit_price=Decimal("1.05"),
    )

    resp = await client.get(f"{BASE}/{prod.id}/prices")
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 2
    assert entries[0]["date"] == "2026-04-01"
    assert entries[0]["supermarket_name"] == "LIDL"
    assert entries[0]["unit_price"] == "1.05"
    assert entries[1]["date"] == "2026-03-01"


async def test_price_history_empty_for_product_without_purchases(
    client: AsyncClient, db_session: AsyncSession
):
    prod = Product(name="Nuevo")
    db_session.add(prod)
    await db_session.flush()
    resp = await client.get(f"{BASE}/{prod.id}/prices")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_price_history_404_for_unknown_product(client: AsyncClient):
    resp = await client.get(f"{BASE}/{uuid.uuid4()}/prices")
    assert resp.status_code == 404
