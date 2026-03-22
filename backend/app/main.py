import logging

from fastapi import FastAPI

from app.api.categories import router as categories_router
from app.api.health import router as health_router
from app.api.products import router as products_router
from app.api.supermarkets import router as supermarkets_router
from app.api.tickets import router as tickets_router
from app.core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Grocery Receipt API",
    description="API para seguimiento de precios de recibos de supermercado",
    version="0.1.0",
    docs_url="/swagger",
)

app.include_router(health_router)
app.include_router(supermarkets_router, prefix="/api/v1")
app.include_router(categories_router, prefix="/api/v1")
app.include_router(products_router, prefix="/api/v1")
app.include_router(tickets_router, prefix="/api/v1")

if not settings.gemini_api_key:
    logger.warning("GEMINI_API_KEY not set — PDF ticket extraction will be unavailable")
