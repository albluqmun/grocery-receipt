import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.line_item import LineItem
from app.models.supermarket import Supermarket
from app.models.ticket import Ticket
from app.schemas.price_history import PriceHistoryEntry


async def get_history(db: AsyncSession, product_id: uuid.UUID) -> list[PriceHistoryEntry]:
    stmt = (
        select(Ticket.date, Supermarket.name, LineItem.unit_price)
        .join(Ticket, LineItem.ticket_id == Ticket.id)
        .join(Supermarket, Ticket.supermarket_id == Supermarket.id)
        .where(LineItem.product_id == product_id)
        .order_by(Ticket.date.desc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        PriceHistoryEntry(date=row[0], supermarket_name=row[1], unit_price=row[2]) for row in rows
    ]
