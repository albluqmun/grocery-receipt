import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.supermarket import Supermarket
from app.models.ticket import Ticket
from app.schemas.line_item import LineItemCreate
from app.schemas.receipt import ExtractedReceipt, ReceiptUploadResponse
from app.schemas.supermarket import SupermarketCreate
from app.schemas.ticket import TicketCreate
from app.services import line_item as line_item_service
from app.services import supermarket as supermarket_service
from app.services import ticket as ticket_service
from app.services.enrichment import enrich_products

logger = logging.getLogger(__name__)

MAX_PDF_SIZE = 10 * 1024 * 1024  # 10 MB


def validate_pdf_bytes(pdf_bytes: bytes) -> str | None:
    """Return an error message if pdf_bytes is not a valid PDF, or None if OK."""
    if not pdf_bytes.startswith(b"%PDF"):
        return "El archivo no es un PDF válido"
    if len(pdf_bytes) > MAX_PDF_SIZE:
        return "El archivo excede el tamaño máximo de 10 MB"
    return None


def compute_pdf_hash(pdf_bytes: bytes) -> str:
    return hashlib.sha256(pdf_bytes).hexdigest()


async def find_by_pdf_hash(db: AsyncSession, pdf_hash: str) -> Ticket | None:
    result = await db.execute(select(Ticket).where(Ticket.pdf_hash == pdf_hash))
    return result.scalar_one_or_none()


async def get_existing_drive_file_ids(db: AsyncSession, candidate_ids: list[str]) -> set[str]:
    """Return the subset of candidate_ids that already exist in the database."""
    if not candidate_ids:
        return set()
    result = await db.execute(
        select(Ticket.drive_file_id).where(Ticket.drive_file_id.in_(candidate_ids))
    )
    return {row[0] for row in result.all()}


async def _find_by_invoice_number(db: AsyncSession, invoice_number: str) -> Ticket | None:
    result = await db.execute(select(Ticket).where(Ticket.invoice_number == invoice_number))
    return result.scalar_one_or_none()


async def _find_or_create_supermarket(
    db: AsyncSession, name: str, locality: str | None
) -> Supermarket:
    result = await db.execute(select(Supermarket).where(Supermarket.name == name))
    existing = result.scalar_one_or_none()
    if existing:
        return existing
    return await supermarket_service.create(db, SupermarketCreate(name=name, locality=locality))


async def _resolve_products(
    db: AsyncSession, names: list[str]
) -> tuple[dict[str, Product], int, int]:
    """Batch find-or-create products. Returns (name→product map, created, matched)."""
    unique_names = list(dict.fromkeys(names))
    result = await db.execute(select(Product).where(Product.name.in_(unique_names)))
    existing = {p.name: p for p in result.scalars().all()}

    new_products = []
    for name in unique_names:
        if name not in existing:
            product = Product(name=name)
            db.add(product)
            new_products.append(product)

    if new_products:
        await db.flush()

    products_map = {**existing, **{p.name: p for p in new_products}}
    matched = sum(1 for n in names if n in existing)
    created = sum(1 for n in names if n not in existing)
    return products_map, created, matched


async def process_extracted_receipt(
    db: AsyncSession,
    data: ExtractedReceipt,
    pdf_hash: str,
    drive_file_id: str | None = None,
) -> ReceiptUploadResponse:
    if data.invoice_number:
        duplicate = await _find_by_invoice_number(db, data.invoice_number)
        if duplicate:
            logger.info(
                "Duplicate ticket (invoice_number=%s): %s", data.invoice_number, duplicate.id
            )
            return ReceiptUploadResponse.duplicate_from(duplicate)

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

    # Collect newly created products for enrichment
    new_products = [
        products_map[name]
        for name in dict.fromkeys(product_names)
        if products_map[name].off_synced_at is None
    ]

    products_enriched = 0
    if new_products:
        try:
            enrichment_result = await enrich_products(
                db, new_products, supermarket_hint=data.supermarket_name
            )
            products_enriched = enrichment_result.enriched
        except Exception:
            logger.warning("Enrichment failed for ticket %s, continuing", ticket.id, exc_info=True)

    logger.info(
        "Ticket %s saved: %d new products, %d matched, %d line items, %d enriched",
        ticket.id,
        products_created,
        products_matched,
        len(data.line_items),
        products_enriched,
    )
    return ReceiptUploadResponse(
        ticket_id=ticket.id,
        supermarket=supermarket.name,
        date=ticket.date,
        total=ticket.total,
        products_created=products_created,
        products_matched=products_matched,
        line_items_count=len(data.line_items),
        products_enriched=products_enriched,
    )
