"""Migration tests on a dedicated database (never touches the shared test DB)."""

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import asyncpg
import pytest
from alembic.config import Config

from alembic import command as _command
from app.core.config import settings

MIG_DB = "grocery_receipt_migtest"


def _in_thread(fn, *args):
    """Run fn in a worker thread: asyncio.run() (here and in alembic's env.py) would
    otherwise unset the main thread's event loop that later async tests rely on."""
    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(fn, *args).result()


class command:  # noqa: N801
    upgrade = staticmethod(lambda *a: _in_thread(_command.upgrade, *a))
    downgrade = staticmethod(lambda *a: _in_thread(_command.downgrade, *a))
    check = staticmethod(lambda *a: _in_thread(_command.check, *a))


def _conn_kwargs(database: str) -> dict:
    p = urlparse(settings.database_url_test)
    return {
        "host": p.hostname,
        "port": p.port or 5432,
        "user": p.username,
        "password": p.password,
        "database": database,
    }


def _admin(sql: str) -> None:
    async def go():
        conn = await asyncpg.connect(**_conn_kwargs("postgres"))
        try:
            await conn.execute(sql)
        finally:
            await conn.close()

    _in_thread(asyncio.run, go())


def _query(sql: str, *args, fetch: bool = True):
    async def go():
        conn = await asyncpg.connect(**_conn_kwargs(MIG_DB))
        try:
            return await (conn.fetch(sql, *args) if fetch else conn.execute(sql, *args))
        finally:
            await conn.close()

    return _in_thread(asyncio.run, go())


@pytest.fixture
def alembic_cfg():
    _admin(f'DROP DATABASE IF EXISTS "{MIG_DB}" WITH (FORCE)')
    _admin(f'CREATE DATABASE "{MIG_DB}"')
    cfg = Config("alembic.ini")
    p = urlparse(settings.database_url_test)
    cfg.set_main_option(
        "sqlalchemy.url",
        f"postgresql://{p.username}:{p.password}@{p.hostname}:{p.port or 5432}/{MIG_DB}",
    )
    yield cfg
    _admin(f'DROP DATABASE IF EXISTS "{MIG_DB}" WITH (FORCE)')


def test_0003_preserves_category_data_on_upgrade_and_downgrade(alembic_cfg):
    command.upgrade(alembic_cfg, "0002")
    cat_id, p_with, p_without = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    _query("INSERT INTO categories (id, name) VALUES ($1, 'Lacteos')", cat_id, fetch=False)
    _query(
        "INSERT INTO products (id, name, category_id) VALUES ($1, 'LECHE', $2)",
        p_with,
        cat_id,
        fetch=False,
    )
    _query("INSERT INTO products (id, name) VALUES ($1, 'SIN CAT')", p_without, fetch=False)

    command.upgrade(alembic_cfg, "0003")
    rows = _query("SELECT product_id, category_id FROM product_categories")
    assert [(r["product_id"], r["category_id"]) for r in rows] == [(p_with, cat_id)]

    command.downgrade(alembic_cfg, "0002")
    rows = _query("SELECT id, category_id FROM products")
    restored = {r["id"]: r["category_id"] for r in rows}
    assert restored == {p_with: cat_id, p_without: None}


def test_new_indexes_upgrade_and_downgrade(alembic_cfg):
    command.upgrade(alembic_cfg, "head")
    names = {r["indexname"] for r in _query("SELECT indexname FROM pg_indexes")}
    for idx in (
        "ix_products_name",
        "ix_products_off_synced_at",
        "ix_tickets_date",
        "ix_line_items_product_id_ticket_id",
        "ix_product_categories_category_id",
    ):
        assert idx in names

    command.downgrade(alembic_cfg, "0003")
    names = {r["indexname"] for r in _query("SELECT indexname FROM pg_indexes")}
    assert "ix_products_name" not in names
    assert "ix_product_categories_category_id" in names


def test_models_match_migrations(alembic_cfg):
    """Equivalent of `alembic check`: autogenerate must find no pending changes."""
    command.upgrade(alembic_cfg, "head")
    command.check(alembic_cfg)
