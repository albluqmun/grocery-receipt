import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import conflict, not_found
from app.core.database import get_db
from app.schemas.pagination import PaginatedResponse, Pagination, pagination_params
from app.schemas.supermarket import SupermarketRead
from app.services import supermarket as supermarket_service

router = APIRouter(prefix="/supermarkets", tags=["supermarkets"])


@router.get("", response_model=PaginatedResponse[SupermarketRead])
async def list_supermarkets(
    pagination: Pagination = Depends(pagination_params),
    db: AsyncSession = Depends(get_db),
):
    items, total = await supermarket_service.get_list(
        db, skip=pagination.skip, limit=pagination.limit
    )
    return PaginatedResponse(items=items, total=total, skip=pagination.skip, limit=pagination.limit)


@router.get("/{supermarket_id}", response_model=SupermarketRead)
async def get_supermarket(supermarket_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    supermarket = await supermarket_service.get_by_id(db, supermarket_id)
    if not supermarket:
        raise not_found("Supermercado")
    return supermarket


@router.delete("/{supermarket_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_supermarket(supermarket_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        deleted = await supermarket_service.delete(db, supermarket_id)
    except IntegrityError:
        raise conflict("No se puede eliminar: tiene tickets asociados")
    if not deleted:
        raise not_found("Supermercado")
