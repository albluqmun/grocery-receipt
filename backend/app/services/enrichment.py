import asyncio
import datetime
import logging

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.line_item import LineItem
from app.models.product import Product
from app.models.supermarket import Supermarket
from app.models.ticket import Ticket
from app.schemas.enrichment import EnrichmentResult, OFFCandidate
from app.services.gemini import match_products_with_off
from app.services.openfoodfacts import OFF_TIMEOUT, REQUEST_DELAY, search_products

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

    # Find existing categories
    result = await db.execute(select(Category).where(Category.name.in_(names)))
    existing = {cat.name: cat for cat in result.scalars().all()}

    # Create missing categories
    for name in names:
        if name not in existing:
            cat = Category(name=name)
            db.add(cat)
            existing[name] = cat

    if existing:
        await db.flush()

    # Ensure the relationship is loaded before assigning (avoid sync lazy-load)
    await db.refresh(product, ["categories"])
    product.categories = list(existing.values())


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

    # Step 1: Search OFF for each product (spaced to stay within rate limit)
    all_candidates: dict[str, list[OFFCandidate]] = {}
    async with httpx.AsyncClient(timeout=OFF_TIMEOUT) as http_client:
        for i, product in enumerate(pending):
            if i > 0:
                await asyncio.sleep(REQUEST_DELAY)
            candidates = await search_products(product.name, client=http_client)
            if candidates:
                all_candidates[product.name] = candidates

    # Products with no OFF results at all — mark synced, no match
    products_without_candidates = [p for p in pending if p.name not in all_candidates]
    now = datetime.datetime.now(datetime.UTC)
    for product in products_without_candidates:
        product.off_synced_at = now

    if not all_candidates:
        await db.flush()
        return EnrichmentResult(
            processed=len(pending),
            enriched=0,
            not_found=len(pending),
            skipped=skipped,
        )

    # Step 2: Ask Gemini to match
    gemini_input: dict[str, list[OFFCandidate]] = {}
    for product in pending:
        if product.name in all_candidates:
            key = f"{product.name} ({supermarket_hint})" if supermarket_hint else product.name
            gemini_input[key] = all_candidates[product.name]

    matches = await match_products_with_off(gemini_input)
    failed = len(matches) == 0 and len(gemini_input) > 0

    # Step 3: Apply matches
    enriched = 0
    candidates_flat = {c.code: c for candidates in all_candidates.values() for c in candidates}

    for product in pending:
        if product.name not in all_candidates:
            continue  # Already handled above

        key = f"{product.name} ({supermarket_hint})" if supermarket_hint else product.name
        matched_code = matches.get(key)

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
        processed=len(pending),
        enriched=enriched,
        not_found=len(pending) - enriched,
        skipped=skipped,
        failed=failed,
    )


async def enrich_pending(
    db: AsyncSession,
    limit: int = 10,
) -> EnrichmentResult:
    """Enrich up to `limit` products that haven't been synced yet."""
    result = await db.execute(select(Product).where(Product.off_synced_at.is_(None)).limit(limit))
    products = list(result.scalars().all())

    if not products:
        return EnrichmentResult(processed=0, enriched=0, not_found=0, skipped=0)

    # Get supermarket hint per product via line_items -> tickets -> supermarkets
    product_supermarkets: dict[str, str | None] = {}
    for product in products:
        stmt = (
            select(Ticket.supermarket_id)
            .join(LineItem, LineItem.ticket_id == Ticket.id)
            .where(LineItem.product_id == product.id)
            .order_by(Ticket.date.desc())
            .limit(1)
        )
        ticket_result = await db.execute(stmt)
        supermarket_id = ticket_result.scalar_one_or_none()
        if supermarket_id:
            supermarket = await db.get(Supermarket, supermarket_id)
            product_supermarkets[product.name] = supermarket.name if supermarket else None
        else:
            product_supermarkets[product.name] = None

    # Build candidates with per-product supermarket context
    all_candidates: dict[str, list[OFFCandidate]] = {}
    pending_with_candidates: list[Product] = []
    now = datetime.datetime.now(datetime.UTC)

    async with httpx.AsyncClient(timeout=OFF_TIMEOUT) as http_client:
        for i, product in enumerate(products):
            if i > 0:
                await asyncio.sleep(REQUEST_DELAY)
            candidates = await search_products(product.name, client=http_client)
            if candidates:
                sm = product_supermarkets.get(product.name)
                key = f"{product.name} ({sm})" if sm else product.name
                all_candidates[key] = candidates
                pending_with_candidates.append(product)
            else:
                product.off_synced_at = now

    if not all_candidates:
        await db.flush()
        return EnrichmentResult(
            processed=len(products), enriched=0, not_found=len(products), skipped=0
        )

    matches = await match_products_with_off(all_candidates)
    failed = len(matches) == 0 and len(all_candidates) > 0

    enriched = 0
    candidates_flat = {c.code: c for cands in all_candidates.values() for c in cands}

    for product in pending_with_candidates:
        sm = product_supermarkets.get(product.name)
        key = f"{product.name} ({sm})" if sm else product.name
        matched_code = matches.get(key)

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
        processed=len(products),
        enriched=enriched,
        not_found=len(products) - enriched,
        skipped=0,
        failed=failed,
    )


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
