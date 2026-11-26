from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings

PUBLIC_PATHS: frozenset[str] = frozenset({"/health", "/swagger", "/openapi.json", "/redoc"})


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Enforce X-API-Key on all non-public paths when settings.api_key is set.

    When settings.api_key is empty the middleware is a no-op (dev mode).
    """

    async def dispatch(self, request: Request, call_next):
        if not settings.api_key:
            return await call_next(request)
        if request.method == "OPTIONS" or request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        if request.headers.get("X-API-Key") != settings.api_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "API key inválida o ausente"},
            )
        return await call_next(request)
