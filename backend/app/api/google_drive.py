import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_gemini
from app.core.config import settings
from app.core.database import get_db
from app.schemas.google_drive import DriveSyncResponse
from app.services.google_drive import sync_drive_folder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tickets/drive", tags=["google-drive"])


@router.post(
    "/sync",
    response_model=DriveSyncResponse,
    status_code=status.HTTP_200_OK,
    summary="Sincronizar tickets PDF desde Google Drive",
)
async def sync_from_drive(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_gemini),
):
    if not settings.google_drive_credentials_path or not settings.google_drive_folder_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de Google Drive no configurado "
            "(faltan GOOGLE_DRIVE_CREDENTIALS_PATH o GOOGLE_DRIVE_FOLDER_ID)",
        )

    return await sync_drive_folder(db)
