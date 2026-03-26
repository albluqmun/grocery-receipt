import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from google.genai.errors import APIError as GeminiAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_gemini
from app.api.exceptions import not_found
from app.core.database import get_db
from app.schemas.pagination import PaginatedResponse
from app.schemas.receipt import ReceiptUploadResponse
from app.schemas.ticket import TicketRead
from app.services import ticket as ticket_service
from app.services.gemini import ReceiptParseError, extract_receipt_from_pdf
from app.services.receipt import (
    compute_pdf_hash,
    find_by_pdf_hash,
    process_extracted_receipt,
    validate_pdf_bytes,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.post(
    "/upload",
    response_model=ReceiptUploadResponse,
    status_code=status.HTTP_200_OK,
    summary="Subir ticket PDF para extracción automática",
)
async def upload_ticket(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_gemini),
):
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Solo se aceptan archivos PDF",
        )

    pdf_bytes = await file.read()

    validation_error = validate_pdf_bytes(pdf_bytes)
    if validation_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=validation_error,
        )

    pdf_hash = compute_pdf_hash(pdf_bytes)

    existing = await find_by_pdf_hash(db, pdf_hash)
    if existing:
        logger.info("Duplicate PDF (hash match), existing ticket: %s", existing.id)
        return ReceiptUploadResponse.duplicate_from(existing)

    try:
        extracted = await extract_receipt_from_pdf(pdf_bytes)
    except GeminiAPIError:
        logger.exception("Gemini API error during PDF extraction")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Error en el servicio de extracción. Inténtelo de nuevo más tarde.",
        )
    except ReceiptParseError:
        logger.exception("Failed to parse Gemini response")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="No se pudo extraer datos del ticket. "
            "Verifique que el PDF es un ticket de supermercado válido.",
        )

    return await process_extracted_receipt(db, extracted, pdf_hash)


@router.get("", response_model=PaginatedResponse[TicketRead])
async def list_tickets(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await ticket_service.get_list(db, skip=skip, limit=limit)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@router.get("/{ticket_id}", response_model=TicketRead)
async def get_ticket(ticket_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    ticket = await ticket_service.get_by_id(db, ticket_id)
    if not ticket:
        raise not_found("Ticket")
    return ticket


@router.delete("/{ticket_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ticket(ticket_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    deleted = await ticket_service.delete(db, ticket_id)
    if not deleted:
        raise not_found("Ticket")
