import datetime
import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from app.core.config import settings
from app.core.database import Base, get_db
from app.main import app

# Import all models so Base.metadata knows about them
from app.models import Category, LineItem, Product, Supermarket, Ticket  # noqa: F401
from app.schemas.receipt import ExtractedLineItem, ExtractedReceipt


def make_extracted_receipt(
    invoice_number: str | None = None,
    supermarket_name: str = "MERCADONA",
    total: Decimal = Decimal("42.50"),
) -> ExtractedReceipt:
    """Build a mock ExtractedReceipt for tests."""
    return ExtractedReceipt(
        supermarket_name=supermarket_name,
        supermarket_locality="TOMARES",
        invoice_number=invoice_number,
        date=datetime.date(2026, 3, 21),
        total=total,
        line_items=[
            ExtractedLineItem(
                product_name="LECHE ENTERA",
                quantity=Decimal("2"),
                unit_price=Decimal("1.10"),
                line_total=Decimal("2.20"),
            ),
        ],
    )


def unique_pdf() -> bytes:
    """Generate a unique PDF payload to avoid hash-based dedup between tests."""
    return b"%PDF-1.4 fake " + uuid.uuid4().hex.encode()


def _run_test_migrations() -> None:
    """Run Alembic migrations against the test database (sync, called before event loop)."""
    cfg = Config("alembic.ini")
    # Use sync driver — Alembic's env.py calls asyncio.run() which can't nest
    sync_url = settings.database_url_test.replace("+asyncpg", "")
    cfg.set_main_option("sqlalchemy.url", sync_url)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session", autouse=True)
def _apply_migrations():
    """Run Alembic migrations on the test DB once per session (sync, before event loop)."""
    _run_test_migrations()


@pytest.fixture(scope="session")
async def engine(_apply_migrations):
    eng = create_async_engine(settings.database_url_test, echo=False)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession]:
    # Clean all tables before each test for full isolation
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient]:
    async def override_get_db() -> AsyncGenerator[AsyncSession]:
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
