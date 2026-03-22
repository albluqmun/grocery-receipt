import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import not_found
from app.core.database import get_db
from app.schemas.pagination import PaginatedResponse
from app.schemas.ticket import TicketRead
from app.services import ticket as ticket_service

router = APIRouter(prefix="/tickets", tags=["tickets"])


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
