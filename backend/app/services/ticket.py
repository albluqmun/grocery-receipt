import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ticket import Ticket
from app.schemas.ticket import TicketCreate, TicketUpdate


async def create(db: AsyncSession, data: TicketCreate) -> Ticket:
    ticket = Ticket(**data.model_dump())
    db.add(ticket)
    await db.flush()
    return ticket


async def get_by_id(db: AsyncSession, ticket_id: uuid.UUID) -> Ticket | None:
    return await db.get(Ticket, ticket_id)


async def get_list(db: AsyncSession, skip: int = 0, limit: int = 20) -> tuple[list[Ticket], int]:
    total = await db.scalar(select(func.count()).select_from(Ticket))
    result = await db.execute(select(Ticket).order_by(Ticket.date.desc()).offset(skip).limit(limit))
    return list(result.scalars().all()), total or 0


async def update(db: AsyncSession, ticket_id: uuid.UUID, data: TicketUpdate) -> Ticket | None:
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(ticket, field, value)
    await db.flush()
    await db.refresh(ticket)
    return ticket


async def delete(db: AsyncSession, ticket_id: uuid.UUID) -> bool:
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        return False
    await db.delete(ticket)
    await db.flush()
    return True
