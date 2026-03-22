import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.schemas.category import CategoryCreate, CategoryUpdate


async def create(db: AsyncSession, data: CategoryCreate) -> Category:
    category = Category(**data.model_dump())
    db.add(category)
    await db.flush()
    return category


async def get_by_id(db: AsyncSession, category_id: uuid.UUID) -> Category | None:
    return await db.get(Category, category_id)


async def get_list(db: AsyncSession, skip: int = 0, limit: int = 20) -> tuple[list[Category], int]:
    total = await db.scalar(select(func.count()).select_from(Category))
    result = await db.execute(select(Category).order_by(Category.name).offset(skip).limit(limit))
    return list(result.scalars().all()), total or 0


async def update(db: AsyncSession, category_id: uuid.UUID, data: CategoryUpdate) -> Category | None:
    category = await db.get(Category, category_id)
    if not category:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(category, field, value)
    await db.flush()
    await db.refresh(category)
    return category


async def delete(db: AsyncSession, category_id: uuid.UUID) -> bool:
    category = await db.get(Category, category_id)
    if not category:
        return False
    await db.delete(category)
    await db.flush()
    return True
