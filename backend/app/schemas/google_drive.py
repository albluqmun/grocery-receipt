from collections import Counter
from enum import StrEnum

from pydantic import BaseModel

from app.schemas.receipt import ReceiptUploadResponse


class DriveFile(BaseModel):
    """Metadata of a file in Google Drive."""

    id: str
    name: str


class SyncFileStatus(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    ERROR = "error"


class SyncErrorCode(StrEnum):
    INVALID_PDF = "invalid_pdf"
    RATE_LIMIT = "rate_limit"
    GEMINI_ERROR = "gemini_error"
    PARSE_ERROR = "parse_error"
    INTERNAL_ERROR = "internal_error"


class DriveSyncFileResult(BaseModel):
    """Result of processing a single Drive file."""

    file_name: str
    status: SyncFileStatus
    detail: ReceiptUploadResponse | None = None
    error_code: SyncErrorCode | None = None
    error_detail: str | None = None


class DriveSyncResponse(BaseModel):
    """Response from the Drive sync endpoint."""

    files_found: int
    files_processed: int
    files_duplicate: int
    files_error: int
    files_skipped: int
    results: list[DriveSyncFileResult]

    @staticmethod
    def from_results(
        files_found: int, results: list[DriveSyncFileResult], files_skipped: int = 0
    ) -> "DriveSyncResponse":
        counts = Counter(r.status for r in results)
        return DriveSyncResponse(
            files_found=files_found,
            files_processed=counts[SyncFileStatus.PROCESSED],
            files_duplicate=counts[SyncFileStatus.DUPLICATE],
            files_error=counts[SyncFileStatus.ERROR],
            files_skipped=files_skipped,
            results=results,
        )
