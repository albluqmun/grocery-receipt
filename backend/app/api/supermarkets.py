import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import conflict, not_found
from app.core.database import get_db
from app.schemas.pagination import PaginatedResponse
from app.schemas.supermarket import SupermarketRead
from app.services import supermarket as supermarket_service

router = APIRouter(prefix="/supermarkets", tags=["supermarkets"])


@router.get("", response_model=PaginatedResponse[SupermarketRead])
async def list_supermarkets(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await supermarket_service.get_list(db, skip=skip, limit=limit)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


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
