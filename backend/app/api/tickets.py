import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from google.genai.errors import APIError as GeminiAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_gemini
from app.api.exceptions import not_found
from app.core.database import get_db
from app.schemas.pagination import PaginatedResponse, Pagination, pagination_params
from app.schemas.receipt import ReceiptUploadResponse
from app.schemas.ticket import TicketRead
from app.services import gemini as gemini_service
from app.services import receipt as receipt_service
from app.services import ticket as ticket_service
from app.services.gemini import ReceiptParseError
from app.services.receipt import InvalidPdfError

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

    try:
        receipt_service.validate_pdf_bytes(pdf_bytes)
    except InvalidPdfError as exc:
        detail = (
            "El archivo no es un PDF válido"
            if str(exc) == "not_pdf"
            else "El archivo excede el tamaño máximo de 10 MB"
        )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)

    pdf_hash = receipt_service.compute_pdf_hash(pdf_bytes)

    existing = await ticket_service.find_by_pdf_hash(db, pdf_hash)
    if existing:
        logger.info("Duplicate PDF (hash match), existing ticket: %s", existing.id)
        return ticket_service.receipt_from_duplicate(existing)

    try:
        extracted = await gemini_service.extract_receipt_from_pdf(pdf_bytes)
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

    return await receipt_service.process_extracted_receipt(db, extracted, pdf_hash)


@router.get("", response_model=PaginatedResponse[TicketRead])
async def list_tickets(
    pagination: Pagination = Depends(pagination_params),
    db: AsyncSession = Depends(get_db),
):
    items, total = await ticket_service.get_list(db, skip=pagination.skip, limit=pagination.limit)
    return PaginatedResponse(items=items, total=total, skip=pagination.skip, limit=pagination.limit)


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
