import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.core.config import settings
from app.core.database import Base
from app.models import *  # noqa: F401, F403

target_metadata = Base.metadata


def _get_url() -> str:
    """Return the database URL, preferring the Alembic config override if set."""
    url = context.config.get_main_option("sqlalchemy.url")
    return url if url else settings.database_url


def run_migrations_offline():
    context.configure(url=_get_url(), target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    url = _get_url()
    # Config override uses sync URL; convert to async for the engine
    async_url = (
        url.replace("postgresql://", "postgresql+asyncpg://") if "+asyncpg" not in url else url
    )
    connectable = create_async_engine(async_url)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
