import logging

from google.genai.errors import APIError as GeminiAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.schemas.google_drive import (
    DriveFile,
    DriveSyncFileResult,
    DriveSyncResponse,
    SyncErrorCode,
    SyncFileStatus,
)
from app.schemas.receipt import ReceiptUploadResponse
from app.services.gemini import ReceiptParseError, extract_receipt_from_pdf
from app.services.google_drive_client import download_file, list_pdf_files
from app.services.receipt import (
    InvalidPdfError,
    compute_pdf_hash,
    process_extracted_receipt,
    validate_pdf_bytes,
)
from app.services.ticket import find_by_pdf_hash, get_existing_drive_file_ids

logger = logging.getLogger(__name__)


async def _process_single_file(db: AsyncSession, df: DriveFile) -> DriveSyncFileResult:
    """Download, validate, extract, and persist a single Drive PDF."""
    pdf_bytes = await download_file(df.id)

    try:
        validate_pdf_bytes(pdf_bytes)
    except InvalidPdfError as exc:
        detail = (
            "El archivo no es un PDF válido"
            if str(exc) == "not_pdf"
            else "El archivo excede el tamaño máximo de 10 MB"
        )
        return DriveSyncFileResult(
            file_name=df.name,
            status=SyncFileStatus.ERROR,
            error_code=SyncErrorCode.INVALID_PDF,
            error_detail=detail,
        )

    pdf_hash = compute_pdf_hash(pdf_bytes)

    existing = await find_by_pdf_hash(db, pdf_hash)
    if existing:
        logger.info("Duplicate PDF hash for '%s', ticket=%s", df.name, existing.id)
        return DriveSyncFileResult(
            file_name=df.name,
            status=SyncFileStatus.DUPLICATE,
            detail=ReceiptUploadResponse.duplicate_from(existing),
        )

    extracted = await extract_receipt_from_pdf(pdf_bytes)
    response = await process_extracted_receipt(db, extracted, pdf_hash, drive_file_id=df.id)

    result_status = SyncFileStatus.DUPLICATE if response.duplicate else SyncFileStatus.PROCESSED
    return DriveSyncFileResult(file_name=df.name, status=result_status, detail=response)


async def sync_drive_folder(db: AsyncSession) -> DriveSyncResponse:
    """Sync new PDF tickets from the configured Google Drive folder."""
    drive_files = await list_pdf_files(settings.google_drive_folder_id)
    logger.info("Found %d PDF files in Drive folder", len(drive_files))

    all_drive_ids = [df.id for df in drive_files]
    known_ids = await get_existing_drive_file_ids(db, all_drive_ids)
    pending = [df for df in drive_files if df.id not in known_ids]

    # Process oldest first so invoice_number dedup catches the earliest ticket
    pending.reverse()

    # Apply batch limit (0 = unlimited)
    files_skipped = 0
    if settings.gemini_batch_limit > 0 and len(pending) > settings.gemini_batch_limit:
        files_skipped = len(pending) - settings.gemini_batch_limit
        pending = pending[: settings.gemini_batch_limit]
        logger.info(
            "Batch limit %d applied: processing %d files, skipping %d",
            settings.gemini_batch_limit,
            len(pending),
            files_skipped,
        )

    results: list[DriveSyncFileResult] = []
    for df in pending:
        try:
            async with db.begin_nested():
                result = await _process_single_file(db, df)
        except GeminiAPIError as exc:
            logger.exception("Gemini API error for '%s' (id=%s)", df.name, df.id)
            error_code = SyncErrorCode.RATE_LIMIT if exc.code == 429 else SyncErrorCode.GEMINI_ERROR
            result = DriveSyncFileResult(
                file_name=df.name,
                status=SyncFileStatus.ERROR,
                error_code=error_code,
                error_detail=exc.message or str(exc),
            )
        except ReceiptParseError as exc:
            logger.exception("Parse error for '%s' (id=%s)", df.name, df.id)
            result = DriveSyncFileResult(
                file_name=df.name,
                status=SyncFileStatus.ERROR,
                error_code=SyncErrorCode.PARSE_ERROR,
                error_detail=str(exc),
            )
        except Exception:
            logger.exception("Unexpected error for '%s' (id=%s)", df.name, df.id)
            result = DriveSyncFileResult(
                file_name=df.name,
                status=SyncFileStatus.ERROR,
                error_code=SyncErrorCode.INTERNAL_ERROR,
                error_detail="Error inesperado al procesar el ticket",
            )
        results.append(result)

    return DriveSyncResponse.from_results(
        files_found=len(drive_files), results=results, files_skipped=files_skipped
    )
