import asyncio
import io

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from pydantic import BaseModel

from app.core.config import settings

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


class DriveFile(BaseModel):
    """Metadata of a file in Google Drive."""

    id: str
    name: str


_service = None


def _get_service():
    """Lazily initialize the Google Drive API service (singleton)."""
    global _service
    if _service is None:
        credentials = service_account.Credentials.from_service_account_file(
            settings.google_drive_credentials_path, scopes=SCOPES
        )
        _service = build("drive", "v3", credentials=credentials)
    return _service


def _list_pdf_files_sync(folder_id: str) -> list[DriveFile]:
    """List PDF files in a Drive folder, ordered by createdTime desc."""
    service = _get_service()
    query = f"'{folder_id}' in parents and mimeType='application/pdf' and trashed=false"
    files: list[DriveFile] = []
    page_token = None

    while True:
        response = (
            service.files()
            .list(
                q=query,
                fields="nextPageToken, files(id, name)",
                orderBy="createdTime desc",
                pageSize=100,
                pageToken=page_token,
            )
            .execute()
        )
        for f in response.get("files", []):
            files.append(DriveFile(id=f["id"], name=f["name"]))

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return files


def _download_file_sync(file_id: str) -> bytes:
    """Download a file's content from Google Drive."""
    service = _get_service()
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


async def list_pdf_files(folder_id: str) -> list[DriveFile]:
    """List PDF files in a Drive folder (async wrapper)."""
    return await asyncio.to_thread(_list_pdf_files_sync, folder_id)


async def download_file(file_id: str) -> bytes:
    """Download a file from Google Drive (async wrapper)."""
    return await asyncio.to_thread(_download_file_sync, file_id)
