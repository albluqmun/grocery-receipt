from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase


async def get_or_create_many[ModelT: DeclarativeBase](
    db: AsyncSession,
    model: type[ModelT],
    names: list[str],
    factory: Callable[[str], ModelT],
) -> tuple[dict[str, ModelT], set[str]]:
    """Batch find-or-create rows of `model` by their unique `name` column.

    Returns (name -> instance map covering both existing and new rows, set of
    names that were newly created). Flushes if anything was created.
    """
    unique_names = list(dict.fromkeys(names))
    if not unique_names:
        return {}, set()

    result = await db.execute(select(model).where(model.name.in_(unique_names)))
    existing = {row.name: row for row in result.scalars().all()}

    created_names = {name for name in unique_names if name not in existing}
    for name in created_names:
        instance = factory(name)
        db.add(instance)
        existing[name] = instance

    if created_names:
        await db.flush()

    return existing, created_names
