import asyncio
import logging
import re

import httpx

from app.schemas.enrichment import OFFCandidate

logger = logging.getLogger(__name__)

OFF_SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"
OFF_FIELDS = "code,product_name,categories,image_url"
OFF_USER_AGENT = "GroceryReceiptTracker/1.0 (github.com/aluque/grocery-receipt)"
OFF_TIMEOUT = 10.0
_NON_SPANISH_PREFIX_RE = re.compile(r"^[a-z]{2}:")
_MAX_RETRIES = 3
_RETRY_STATUSES = {429, 503}

# Minimum delay between consecutive batch calls (OFF search: ~10 req/min)
REQUEST_DELAY = 6.0

# Regexes for name simplification
_QUANTITY_RE = re.compile(r"\b\d+[.,]?\d*\s*(g|gr|kg|ml|cl|l|ud|uds|unidades)\b", re.IGNORECASE)
_PERCENT_RE = re.compile(r"\d+[.,]?\d*\s*%")
_STANDALONE_NUM_RE = re.compile(r"\b\d+[.,]?\d*\b")


def _filter_spanish_categories(categories: str | None) -> str | None:
    """Keep only categories that don't have a language prefix (assumed Spanish)."""
    if not categories:
        return None
    parts = [c.strip() for c in categories.split(",")]
    spanish = [p for p in parts if not _NON_SPANISH_PREFIX_RE.match(p)]
    return ",".join(spanish) if spanish else None


def _simplify_search_terms(name: str) -> str | None:
    """Produce a simplified search query from a product name.

    Removes quantities, percentages, standalone numbers and truncates to 3 words.
    Returns None if simplification produces no meaningful change.
    """
    simplified = name.lower()
    simplified = _PERCENT_RE.sub("", simplified)
    simplified = _QUANTITY_RE.sub("", simplified)
    simplified = _STANDALONE_NUM_RE.sub("", simplified)
    simplified = " ".join(simplified.split())
    words = simplified.split()
    if len(words) > 3:
        words = words[:3]
    simplified = " ".join(words)
    if not simplified or len(simplified) < 2 or simplified == name.lower():
        return None
    return simplified


async def _do_search(
    search_terms: str,
    max_results: int,
    client: httpx.AsyncClient | None,
) -> list[OFFCandidate]:
    """Execute a single OFF search with retry logic."""
    params = {
        "search_terms": search_terms,
        "search_simple": 1,
        "action": "process",
        "json": 1,
        "page_size": max_results,
        "fields": OFF_FIELDS,
        "lc": "es",
        "cc": "es",
    }
    headers = {"User-Agent": OFF_USER_AGENT}

    for attempt in range(_MAX_RETRIES):
        try:
            if client is not None:
                response = await client.get(OFF_SEARCH_URL, params=params, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=OFF_TIMEOUT) as _client:
                    response = await _client.get(OFF_SEARCH_URL, params=params, headers=headers)
        except Exception:
            logger.warning("Open Food Facts request failed for '%s'", search_terms, exc_info=True)
            return []

        if response.status_code in _RETRY_STATUSES:
            wait = 2**attempt
            logger.warning(
                "OFF returned %d for '%s', retry %d/%d in %ds",
                response.status_code,
                search_terms,
                attempt + 1,
                _MAX_RETRIES,
                wait,
            )
            await asyncio.sleep(wait)
            continue

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            logger.warning(
                "Open Food Facts HTTP error %d for '%s'",
                response.status_code,
                search_terms,
            )
            return []

        data = response.json()
        products = data.get("products", [])

        return [
            OFFCandidate(
                code=p.get("code", ""),
                product_name=p.get("product_name", ""),
                categories=_filter_spanish_categories(p.get("categories")),
                image_url=p.get("image_url"),
            )
            for p in products
            if p.get("code") and p.get("product_name")
        ]

    logger.warning("OFF: max retries exhausted for '%s'", search_terms)
    return []


async def search_products(
    product_name: str,
    max_results: int = 4,
    client: httpx.AsyncClient | None = None,
) -> list[OFFCandidate]:
    """Search Open Food Facts for product candidates.

    Tries the original name first; if no results, retries with simplified terms.
    Returns empty list on any error.
    """
    results = await _do_search(product_name, max_results, client)
    if results:
        return results

    simplified = _simplify_search_terms(product_name)
    if simplified:
        logger.info("OFF: retrying with simplified terms '%s' (was '%s')", simplified, product_name)
        return await _do_search(simplified, max_results, client)

    return []
