from fastapi import HTTPException, status

from app.core.config import settings


def require_gemini() -> None:
    """Raise 503 if Gemini API key is not configured."""
    if not settings.gemini_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de extracción no configurado (falta GEMINI_API_KEY)",
        )
