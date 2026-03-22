import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.supermarket import Supermarket
from app.schemas.supermarket import SupermarketCreate, SupermarketUpdate


async def create(db: AsyncSession, data: SupermarketCreate) -> Supermarket:
    supermarket = Supermarket(**data.model_dump())
    db.add(supermarket)
    await db.flush()
    return supermarket


async def get_by_id(db: AsyncSession, supermarket_id: uuid.UUID) -> Supermarket | None:
    return await db.get(Supermarket, supermarket_id)


async def get_list(
    db: AsyncSession, skip: int = 0, limit: int = 20
) -> tuple[list[Supermarket], int]:
    total = await db.scalar(select(func.count()).select_from(Supermarket))
    result = await db.execute(
        select(Supermarket).order_by(Supermarket.name).offset(skip).limit(limit)
    )
    return list(result.scalars().all()), total or 0


async def update(
    db: AsyncSession, supermarket_id: uuid.UUID, data: SupermarketUpdate
) -> Supermarket | None:
    supermarket = await db.get(Supermarket, supermarket_id)
    if not supermarket:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(supermarket, field, value)
    await db.flush()
    await db.refresh(supermarket)
    return supermarket


async def delete(db: AsyncSession, supermarket_id: uuid.UUID) -> bool:
    supermarket = await db.get(Supermarket, supermarket_id)
    if not supermarket:
        return False
    await db.delete(supermarket)
    await db.flush()
    return True
