import datetime
import logging
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.line_item import LineItem
from app.models.product import Product
from app.models.supermarket import Supermarket
from app.models.ticket import Ticket
from app.schemas.enrichment import EnrichmentResult
from app.services.common import get_or_create_many
from app.services.gemini import match_products_with_off
from app.services.openfoodfacts import search_many

logger = logging.getLogger(__name__)


async def _assign_categories(
    db: AsyncSession, product: Product, categories_str: str | None
) -> None:
    """Parse OFF categories string and link them to the product via M2M."""
    if not categories_str:
        return
    names = [name.strip() for name in categories_str.split(",") if name.strip()]
    if not names:
        return

    categories_map, _created = await get_or_create_many(
        db, Category, names, lambda name: Category(name=name)
    )

    # Ensure the relationship is loaded before assigning (avoid sync lazy-load)
    await db.refresh(product, ["categories"])
    product.categories = list(categories_map.values())


def _gemini_key(name: str, hint: str | None) -> str:
    return f"{name} ({hint})" if hint else name


async def _enrich(
    db: AsyncSession,
    products_with_hints: dict[uuid.UUID, tuple[Product, str | None]],
) -> EnrichmentResult:
    """Shared enrichment core: search OFF, match with Gemini, apply results.

    `products_with_hints` maps product.id to (product, supermarket_hint); every
    entry is assumed to need enrichment (callers pre-filter by off_synced_at).
    """
    now = datetime.datetime.now(datetime.UTC)
    names = {pid: product.name for pid, (product, _hint) in products_with_hints.items()}
    candidates_by_id = await search_many(names)

    for pid, (product, _hint) in products_with_hints.items():
        if pid not in candidates_by_id:
            product.off_synced_at = now

    if not candidates_by_id:
        await db.flush()
        return EnrichmentResult(
            processed=len(products_with_hints),
            enriched=0,
            not_found=len(products_with_hints),
            skipped=0,
        )

    def _key(pid: uuid.UUID) -> str:
        product, hint = products_with_hints[pid]
        return _gemini_key(product.name, hint)

    gemini_input = {_key(pid): candidates for pid, candidates in candidates_by_id.items()}
    matches = await match_products_with_off(gemini_input)
    failed = len(matches) == 0 and len(gemini_input) > 0

    candidates_flat = {c.code: c for cands in candidates_by_id.values() for c in cands}

    enriched = 0
    for pid, candidates in candidates_by_id.items():
        product = products_with_hints[pid][0]
        matched_code = matches.get(_key(pid))

        if matched_code and matched_code in candidates_flat:
            off = candidates_flat[matched_code]
            product.off_code = off.code
            product.off_name = off.product_name
            product.off_image_url = off.image_url
            await _assign_categories(db, product, off.categories)
            enriched += 1

        if not failed:
            product.off_synced_at = now

    await db.flush()

    return EnrichmentResult(
        processed=len(products_with_hints),
        enriched=enriched,
        not_found=len(products_with_hints) - enriched,
        skipped=0,
        failed=failed,
    )


async def enrich_products(
    db: AsyncSession,
    products: list[Product],
    supermarket_hint: str | None = None,
) -> EnrichmentResult:
    """Enrich a list of products with Open Food Facts data via Gemini matching."""
    pending = [p for p in products if p.off_synced_at is None]
    skipped = len(products) - len(pending)

    if not pending:
        return EnrichmentResult(processed=0, enriched=0, not_found=0, skipped=skipped)

    products_with_hints = {p.id: (p, supermarket_hint) for p in pending}
    result = await _enrich(db, products_with_hints)
    return result.model_copy(update={"skipped": skipped})


async def enrich_one(db: AsyncSession, product: Product) -> EnrichmentResult:
    """Force re-enrichment of a single product, ignoring any previous sync state."""
    product.off_synced_at = None
    return await enrich_products(db, [product])


async def _supermarket_hints_for(
    db: AsyncSession, product_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str | None]:
    """Return each product's most recent purchase supermarket name, via one query."""
    stmt = (
        select(LineItem.product_id, Supermarket.name, Ticket.date)
        .join(Ticket, Ticket.id == LineItem.ticket_id)
        .join(Supermarket, Supermarket.id == Ticket.supermarket_id)
        .where(LineItem.product_id.in_(product_ids))
        .order_by(LineItem.product_id, Ticket.date.desc())
    )
    result = await db.execute(stmt)
    hints: dict[uuid.UUID, str | None] = {}
    for product_id, supermarket_name, _date in result.all():
        if product_id not in hints:
            hints[product_id] = supermarket_name
    return hints


async def enrich_pending(db: AsyncSession, limit: int = 10) -> EnrichmentResult:
    """Enrich up to `limit` products that haven't been synced yet."""
    result = await db.execute(select(Product).where(Product.off_synced_at.is_(None)).limit(limit))
    products = list(result.scalars().all())

    if not products:
        return EnrichmentResult(processed=0, enriched=0, not_found=0, skipped=0)

    hints = await _supermarket_hints_for(db, [p.id for p in products])
    products_with_hints = {p.id: (p, hints.get(p.id)) for p in products}
    return await _enrich(db, products_with_hints)


async def reset_failed_enrichments(db: AsyncSession) -> int:
    """Clear off_synced_at for products that were synced but got no OFF match.

    Returns the count of products reset.
    """
    stmt = (
        update(Product)
        .where(Product.off_synced_at.is_not(None))
        .where(Product.off_code.is_(None))
        .values(off_synced_at=None)
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount
