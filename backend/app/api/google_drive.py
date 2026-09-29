import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_gemini, require_google_drive
from app.core.database import get_db
from app.schemas.google_drive import DriveSyncResponse
from app.services import google_drive as google_drive_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tickets/drive", tags=["tickets"])


@router.post(
    "/sync",
    response_model=DriveSyncResponse,
    status_code=status.HTTP_200_OK,
    summary="Sincronizar tickets PDF desde Google Drive",
)
async def sync_from_drive(
    db: AsyncSession = Depends(get_db),
    _gemini: None = Depends(require_gemini),
    _drive: None = Depends(require_google_drive),
):
    return await google_drive_service.sync_drive_folder(db)
