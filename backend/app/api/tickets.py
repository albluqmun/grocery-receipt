import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from google.genai.errors import APIError as GeminiAPIError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import not_found
from app.core.config import settings
from app.core.database import get_db
from app.schemas.pagination import PaginatedResponse
from app.schemas.receipt import ReceiptUploadResponse
from app.schemas.ticket import TicketRead
from app.services import ticket as ticket_service
from app.services.gemini import extract_receipt_from_pdf
from app.services.receipt import compute_pdf_hash, find_by_pdf_hash, process_extracted_receipt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tickets", tags=["tickets"])

MAX_PDF_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post(
    "/upload",
    response_model=ReceiptUploadResponse,
    status_code=status.HTTP_200_OK,
    summary="Subir ticket PDF para extracción automática",
)
async def upload_ticket(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
):
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Solo se aceptan archivos PDF",
        )

    if not settings.gemini_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de extracción no configurado (falta GEMINI_API_KEY)",
        )

    pdf_bytes = await file.read()

    if not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="El archivo no es un PDF válido",
        )

    if len(pdf_bytes) > MAX_PDF_SIZE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="El archivo excede el tamaño máximo de 10 MB",
        )

    pdf_hash = compute_pdf_hash(pdf_bytes)

    # Fast path: skip Gemini if exact same PDF was already processed
    existing = await find_by_pdf_hash(db, pdf_hash)
    if existing:
        logger.info("Duplicate PDF (hash match), existing ticket: %s", existing.id)
        return ReceiptUploadResponse(
            ticket_id=existing.id,
            supermarket=existing.supermarket.name,
            date=existing.date,
            total=existing.total,
            products_created=0,
            products_matched=0,
            line_items_count=0,
            duplicate=True,
        )

    try:
        extracted = await extract_receipt_from_pdf(pdf_bytes)
    except GeminiAPIError:
        logger.exception("Gemini API error during PDF extraction")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Error en el servicio de extracción. Inténtelo de nuevo más tarde.",
        )
    except (ValidationError, ValueError):
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
