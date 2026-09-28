from fastapi import HTTPException, status

from app.core.config import settings


def require_gemini() -> None:
    """Raise 503 if Gemini API key is not configured."""
    if not settings.gemini_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de extracción no configurado (falta GEMINI_API_KEY)",
        )


def require_google_drive() -> None:
    """Raise 503 if Google Drive is not configured."""
    if not settings.google_drive_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de Google Drive no configurado "
            "(faltan GOOGLE_DRIVE_CREDENTIALS_PATH o GOOGLE_DRIVE_FOLDER_ID)",
        )
