import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from alembic import command
from alembic.config import Config
from app.api.categories import router as categories_router
from app.api.google_drive import router as google_drive_router
from app.api.health import router as health_router
from app.api.products import router as products_router
from app.api.supermarkets import router as supermarkets_router
from app.api.tickets import router as tickets_router
from app.core.config import settings
from app.core.database import Base, engine
from app.models import Category, LineItem, Product, Supermarket, Ticket  # noqa: F401

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


def _stamp_alembic_head() -> None:
    """Tell Alembic the DB is at the latest revision (no migrations executed)."""
    cfg = Config("alembic.ini")
    command.stamp(cfg, "head")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await asyncio.to_thread(_stamp_alembic_head)
    logger.info("Database tables verified")
    yield


app = FastAPI(
    title="Grocery Receipt API",
    description="API para seguimiento de precios de recibos de supermercado",
    version="0.1.0",
    docs_url="/swagger",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(supermarkets_router, prefix="/api/v1")
app.include_router(categories_router, prefix="/api/v1")
app.include_router(products_router, prefix="/api/v1")
app.include_router(tickets_router, prefix="/api/v1")
app.include_router(google_drive_router, prefix="/api/v1")

if not settings.gemini_api_key:
    logger.warning("GEMINI_API_KEY not set — PDF ticket extraction will be unavailable")

if not settings.google_drive_credentials_path or not settings.google_drive_folder_id:
    logger.warning("Google Drive not configured — Drive sync will be unavailable")
