import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.schemas.product import ProductCreate, ProductUpdate


async def create(db: AsyncSession, data: ProductCreate) -> Product:
    product = Product(**data.model_dump())
    db.add(product)
    await db.flush()
    await db.refresh(product)
    return product


async def get_by_id(db: AsyncSession, product_id: uuid.UUID) -> Product | None:
    return await db.get(Product, product_id)


async def get_list(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 20,
    q: str | None = None,
) -> tuple[list[Product], int]:
    stmt = select(Product)
    count_stmt = select(func.count()).select_from(Product)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        condition = or_(Product.name.ilike(pattern), Product.off_name.ilike(pattern))
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    total = await db.scalar(count_stmt)
    result = await db.execute(stmt.order_by(Product.name).offset(skip).limit(limit))
    return list(result.scalars().all()), total or 0


async def update(db: AsyncSession, product_id: uuid.UUID, data: ProductUpdate) -> Product | None:
    product = await db.get(Product, product_id)
    if not product:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    await db.flush()
    await db.refresh(product)
    return product


async def delete(db: AsyncSession, product_id: uuid.UUID) -> bool:
    product = await db.get(Product, product_id)
    if not product:
        return False
    await db.delete(product)
    await db.flush()
    return True
