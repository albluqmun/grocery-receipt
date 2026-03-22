import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import conflict, not_found
from app.core.database import get_db
from app.schemas.pagination import PaginatedResponse
from app.schemas.product import ProductCreate, ProductRead, ProductUpdate
from app.services import product as product_service

router = APIRouter(prefix="/products", tags=["products"])


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(data: ProductCreate, db: AsyncSession = Depends(get_db)):
    try:
        return await product_service.create(db, data)
    except IntegrityError:
        raise conflict("Categoría referenciada no existe")


@router.get("", response_model=PaginatedResponse[ProductRead])
async def list_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await product_service.get_list(db, skip=skip, limit=limit)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@router.get("/{product_id}", response_model=ProductRead)
async def get_product(product_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    product = await product_service.get_by_id(db, product_id)
    if not product:
        raise not_found("Producto")
    return product


@router.patch("/{product_id}", response_model=ProductRead)
async def update_product(
    product_id: uuid.UUID,
    data: ProductUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        product = await product_service.update(db, product_id, data)
    except IntegrityError:
        raise conflict("Categoría referenciada no existe")
    if not product:
        raise not_found("Producto")
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        deleted = await product_service.delete(db, product_id)
    except IntegrityError:
        raise conflict("No se puede eliminar: tiene líneas de ticket asociadas")
    if not deleted:
        raise not_found("Producto")
