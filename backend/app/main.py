import asyncio
import logging
from contextlib import asynccontextmanager

from alembic.config import Config
from fastapi import FastAPI

from alembic import command
from app.api.categories import router as categories_router
from app.api.google_drive import router as google_drive_router
from app.api.health import router as health_router
from app.api.products import router as products_router
from app.api.supermarkets import router as supermarkets_router
from app.api.tickets import router as tickets_router
from app.core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


def _run_migrations() -> None:
    """Run Alembic migrations to ensure the database schema is up to date."""
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await asyncio.to_thread(_run_migrations)
    logger.info("Database migrations applied")
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
