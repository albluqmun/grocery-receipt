import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_gemini
from app.api.exceptions import conflict, not_found
from app.core.database import get_db
from app.schemas.enrichment import EnrichmentResult, ResetResult
from app.schemas.pagination import PaginatedResponse
from app.schemas.product import ProductCategoryAdd, ProductCreate, ProductRead, ProductUpdate
from app.services import category as category_service
from app.services import product as product_service
from app.services.enrichment import enrich_pending, enrich_products, reset_failed_enrichments

router = APIRouter(prefix="/products", tags=["products"])


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(data: ProductCreate, db: AsyncSession = Depends(get_db)):
    return await product_service.create(db, data)


@router.get("", response_model=PaginatedResponse[ProductRead])
async def list_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await product_service.get_list(db, skip=skip, limit=limit)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@router.post("/enrich", response_model=EnrichmentResult)
async def batch_enrich_products(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_gemini),
):
    return await enrich_pending(db, limit=limit)


@router.post("/enrich/reset", response_model=ResetResult)
async def reset_failed_enrichments_endpoint(
    db: AsyncSession = Depends(get_db),
):
    count = await reset_failed_enrichments(db)
    return ResetResult(reset=count)


@router.post("/{product_id}/enrich", response_model=EnrichmentResult)
async def single_enrich_product(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_gemini),
):
    product = await product_service.get_by_id(db, product_id)
    if not product:
        raise not_found("Producto")
    # Force re-enrichment: clear off_synced_at
    product.off_synced_at = None
    return await enrich_products(db, [product])


@router.post("/{product_id}/categories", response_model=ProductRead, status_code=status.HTTP_200_OK)
async def add_category_to_product(
    product_id: uuid.UUID,
    data: ProductCategoryAdd,
    db: AsyncSession = Depends(get_db),
):
    product = await product_service.get_by_id(db, product_id)
    if not product:
        raise not_found("Producto")

    category = await category_service.get_by_id(db, data.category_id)
    if not category:
        raise not_found("Categoría")

    await db.refresh(product, ["categories"])
    if category in product.categories:
        raise conflict("El producto ya tiene esta categoría asignada")

    product.categories.append(category)
    await db.flush()
    await db.refresh(product)
    return product


@router.delete("/{product_id}/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_category_from_product(
    product_id: uuid.UUID,
    category_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    product = await product_service.get_by_id(db, product_id)
    if not product:
        raise not_found("Producto")

    category = await category_service.get_by_id(db, category_id)
    if not category:
        raise not_found("Categoría")

    await db.refresh(product, ["categories"])
    if category not in product.categories:
        raise not_found("Categoría no asignada al producto")

    product.categories.remove(category)
    await db.flush()


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
    product = await product_service.update(db, product_id, data)
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
