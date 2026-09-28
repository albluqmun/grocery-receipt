import hashlib
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.supermarket import Supermarket
from app.schemas.line_item import LineItemCreate
from app.schemas.receipt import ExtractedReceipt, ReceiptUploadResponse
from app.schemas.supermarket import SupermarketCreate
from app.schemas.ticket import TicketCreate
from app.services import line_item as line_item_service
from app.services import supermarket as supermarket_service
from app.services import ticket as ticket_service
from app.services.common import get_or_create_many

logger = logging.getLogger(__name__)

MAX_PDF_SIZE = 10 * 1024 * 1024  # 10 MB


class InvalidPdfError(ValueError):
    """Raised when uploaded bytes are not a valid, size-bounded PDF."""


def validate_pdf_bytes(pdf_bytes: bytes) -> None:
    """Raise InvalidPdfError if pdf_bytes is not a valid PDF within the size limit."""
    if not pdf_bytes.startswith(b"%PDF"):
        raise InvalidPdfError("not_pdf")
    if len(pdf_bytes) > MAX_PDF_SIZE:
        raise InvalidPdfError("too_large")


def compute_pdf_hash(pdf_bytes: bytes) -> str:
    return hashlib.sha256(pdf_bytes).hexdigest()


async def _find_or_create_supermarket(
    db: AsyncSession, name: str, locality: str | None
) -> Supermarket:
    existing = await supermarket_service.get_by_name(db, name)
    if existing:
        return existing
    return await supermarket_service.create(db, SupermarketCreate(name=name, locality=locality))


async def _resolve_products(
    db: AsyncSession, names: list[str]
) -> tuple[dict[str, Product], int, int]:
    """Batch find-or-create products. Returns (name→product map, created, matched)."""
    products_map, created_names = await get_or_create_many(
        db, Product, names, lambda name: Product(name=name)
    )
    matched = sum(1 for n in names if n not in created_names)
    created = sum(1 for n in names if n in created_names)
    return products_map, created, matched


async def process_extracted_receipt(
    db: AsyncSession,
    data: ExtractedReceipt,
    pdf_hash: str,
    drive_file_id: str | None = None,
) -> ReceiptUploadResponse:
    if data.invoice_number:
        duplicate = await ticket_service.find_by_invoice_number(db, data.invoice_number)
        if duplicate:
            logger.info(
                "Duplicate ticket (invoice_number=%s): %s", data.invoice_number, duplicate.id
            )
            return ticket_service.receipt_from_duplicate(duplicate)

    supermarket = await _find_or_create_supermarket(
        db, data.supermarket_name, data.supermarket_locality
    )

    ticket = await ticket_service.create(
        db,
        TicketCreate(
            date=data.date,
            supermarket_id=supermarket.id,
            total=data.total,
            invoice_number=data.invoice_number,
            pdf_hash=pdf_hash,
            drive_file_id=drive_file_id,
        ),
    )

    product_names = [item.product_name for item in data.line_items]
    products_map, products_created, products_matched = await _resolve_products(db, product_names)

    for item in data.line_items:
        await line_item_service.create(
            db,
            ticket.id,
            LineItemCreate(
                product_id=products_map[item.product_name].id,
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
            ),
        )

    logger.info(
        "Ticket %s saved: %d new products, %d matched, %d line items",
        ticket.id,
        products_created,
        products_matched,
        len(data.line_items),
    )
    return ReceiptUploadResponse(
        ticket_id=ticket.id,
        supermarket=supermarket.name,
        date=ticket.date,
        total=ticket.total,
        products_created=products_created,
        products_matched=products_matched,
        line_items_count=len(data.line_items),
    )
