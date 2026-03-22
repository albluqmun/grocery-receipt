import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.line_item import LineItem
from app.schemas.line_item import LineItemCreate, LineItemUpdate


async def create(db: AsyncSession, ticket_id: uuid.UUID, data: LineItemCreate) -> LineItem:
    line = LineItem(ticket_id=ticket_id, **data.model_dump())
    db.add(line)
    await db.flush()
    return line


async def get_by_id(db: AsyncSession, ticket_id: uuid.UUID, line_id: uuid.UUID) -> LineItem | None:
    result = await db.execute(
        select(LineItem).where(LineItem.ticket_id == ticket_id, LineItem.id == line_id)
    )
    return result.scalar_one_or_none()


async def get_list(
    db: AsyncSession, ticket_id: uuid.UUID, skip: int = 0, limit: int = 20
) -> tuple[list[LineItem], int]:
    base = select(LineItem).where(LineItem.ticket_id == ticket_id)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    result = await db.execute(base.order_by(LineItem.created_at).offset(skip).limit(limit))
    return list(result.scalars().all()), total or 0


async def update(
    db: AsyncSession, ticket_id: uuid.UUID, line_id: uuid.UUID, data: LineItemUpdate
) -> LineItem | None:
    line = await get_by_id(db, ticket_id, line_id)
    if not line:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(line, field, value)
    await db.flush()
    await db.refresh(line)
    return line


async def delete(db: AsyncSession, ticket_id: uuid.UUID, line_id: uuid.UUID) -> bool:
    line = await get_by_id(db, ticket_id, line_id)
    if not line:
        return False
    await db.delete(line)
    await db.flush()
    return True
