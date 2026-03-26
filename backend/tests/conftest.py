import datetime
import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
async def engine():
    eng = create_async_engine(settings.database_url, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession]:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    # Clean up after test
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


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
