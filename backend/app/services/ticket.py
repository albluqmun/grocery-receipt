import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ticket import Ticket
from app.schemas.receipt import ReceiptUploadResponse
from app.schemas.ticket import TicketCreate, TicketUpdate


async def create(db: AsyncSession, data: TicketCreate) -> Ticket:
    ticket = Ticket(**data.model_dump())
    db.add(ticket)
    await db.flush()
    return ticket


async def get_by_id(db: AsyncSession, ticket_id: uuid.UUID) -> Ticket | None:
    return await db.get(Ticket, ticket_id)


async def get_list(db: AsyncSession, skip: int = 0, limit: int = 20) -> tuple[list[Ticket], int]:
    total = await db.scalar(select(func.count()).select_from(Ticket))
    result = await db.execute(select(Ticket).order_by(Ticket.date.desc()).offset(skip).limit(limit))
    return list(result.scalars().all()), total or 0


async def find_by_pdf_hash(db: AsyncSession, pdf_hash: str) -> Ticket | None:
    result = await db.execute(
        select(Ticket).options(selectinload(Ticket.supermarket)).where(Ticket.pdf_hash == pdf_hash)
    )
    return result.scalar_one_or_none()


async def find_by_invoice_number(db: AsyncSession, invoice_number: str) -> Ticket | None:
    result = await db.execute(
        select(Ticket)
        .options(selectinload(Ticket.supermarket))
        .where(Ticket.invoice_number == invoice_number)
    )
    return result.scalar_one_or_none()


async def get_existing_drive_file_ids(db: AsyncSession, candidate_ids: list[str]) -> set[str]:
    """Return the subset of candidate_ids that already exist in the database."""
    if not candidate_ids:
        return set()
    result = await db.execute(
        select(Ticket.drive_file_id).where(Ticket.drive_file_id.in_(candidate_ids))
    )
    return {row[0] for row in result.all()}


async def update(db: AsyncSession, ticket_id: uuid.UUID, data: TicketUpdate) -> Ticket | None:
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(ticket, field, value)
    await db.flush()
    await db.refresh(ticket)
    return ticket


async def delete(db: AsyncSession, ticket_id: uuid.UUID) -> bool:
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        return False
    await db.delete(ticket)
    await db.flush()
    return True


def receipt_from_duplicate(ticket: Ticket) -> ReceiptUploadResponse:
    return ReceiptUploadResponse(
        ticket_id=ticket.id,
        supermarket=ticket.supermarket.name,
        date=ticket.date,
        total=ticket.total,
        products_created=0,
        products_matched=0,
        line_items_count=0,
        duplicate=True,
    )
