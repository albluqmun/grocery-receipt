import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import conflict, not_found
from app.core.database import get_db
from app.schemas.category import CategoryCreate, CategoryRead, CategoryUpdate
from app.schemas.pagination import PaginatedResponse
from app.services import category as category_service

router = APIRouter(prefix="/categories", tags=["categories"])


@router.post("", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
async def create_category(data: CategoryCreate, db: AsyncSession = Depends(get_db)):
    try:
        return await category_service.create(db, data)
    except IntegrityError:
        raise conflict("Ya existe una categoría con ese nombre")


@router.get("", response_model=PaginatedResponse[CategoryRead])
async def list_categories(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await category_service.get_list(db, skip=skip, limit=limit)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@router.get("/{category_id}", response_model=CategoryRead)
async def get_category(category_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    category = await category_service.get_by_id(db, category_id)
    if not category:
        raise not_found("Categoría")
    return category


@router.patch("/{category_id}", response_model=CategoryRead)
async def update_category(
    category_id: uuid.UUID,
    data: CategoryUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        category = await category_service.update(db, category_id, data)
    except IntegrityError:
        raise conflict("Ya existe una categoría con ese nombre")
    if not category:
        raise not_found("Categoría")
    return category


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(category_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        deleted = await category_service.delete(db, category_id)
    except IntegrityError:
        raise conflict("No se puede eliminar: tiene productos asociados")
    if not deleted:
        raise not_found("Categoría")
