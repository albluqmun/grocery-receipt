from fastapi import FastAPI

from app.api.health import router as health_router

app = FastAPI(
    title="Grocery Receipt API",
    description="API para seguimiento de precios de recibos de supermercado",
    version="0.1.0",
    docs_url="/swagger",
)

app.include_router(health_router)
