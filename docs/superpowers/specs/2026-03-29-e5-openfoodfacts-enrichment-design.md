# E5 — Open Food Facts Product Enrichment

## Summary

Enrich products extracted from grocery receipts with data from Open Food Facts (OFF).
Uses Gemini as an arbitrator to select the best match from OFF search results,
given the abbreviated product names that appear on supermarket tickets.

## Problem

Products created from ticket extraction have short, abbreviated names (e.g., "CACAHUETE SIN SAL")
with no images, categories, or barcode. Open Food Facts has this data but search results are fuzzy
— multiple candidates may match. Gemini resolves ambiguity by choosing the best match.

## Data Model

Add nullable columns to `products` table (migration `0002_add_off_fields_to_products`):

| Column | Type | Description |
|---|---|---|
| `off_code` | `String(50)` | EAN barcode from OFF |
| `off_name` | `String(300)` | Canonical product name from OFF |
| `off_image_url` | `Text` | Product image URL |
| `off_categories` | `Text` | Categories in Spanish, comma-separated |
| `off_synced_at` | `DateTime(timezone=True)` | Timestamp of enrichment attempt |

**State logic:**

- `off_synced_at IS NULL` — never attempted (pending enrichment)
- `off_synced_at IS NOT NULL AND off_code IS NULL` — attempted, no match found
- `off_synced_at IS NOT NULL AND off_code IS NOT NULL` — enriched successfully

## Architecture

### Service: `app/services/openfoodfacts.py`

```python
async def search_products(product_name: str, max_results: int = 4) -> list[OFFCandidate]
```

- Calls `https://world.openfoodfacts.org/cgi/search.pl` with `search_terms`, `json=1`, `page_size`
- Requested fields: `code`, `product_name`, `categories`, `image_url`, `stores`
- Filters categories to Spanish only (discards entries prefixed with `en:`, `pt:`, `fr:`, etc.)
- Returns `list[OFFCandidate]`; empty list on API failure or no results (never raises)
- HTTP client: `httpx.AsyncClient`

### Service: `app/services/gemini.py` (new function)

```python
async def match_products_with_off(
    candidates: dict[str, list[OFFCandidate]],
    supermarket_name: str | None = None,
) -> dict[str, str | None]
```

- **Input:** dict where key = our `product.name`, value = list of OFF candidates
- **Output:** dict where key = our `product.name`, value = chosen `off_code` or `None`
- Sends a single prompt with all products and their candidates in one batch
- Includes supermarket name per product for disambiguation (e.g., Mercadona -> Hacendado)
- Uses `response_mime_type="application/json"` with schema validation
- On `GeminiAPIError`: returns empty dict (products stay with `off_synced_at = NULL` for retry)

**Prompt structure:**

```
These products were purchased at a Spanish supermarket. For each product,
choose the best matching Open Food Facts candidate or respond null if none match.
Consider the supermarket name as a hint for the brand.
Respond as JSON: {"product_name": "ean_code_or_null", ...}

1. CACAHUETE SIN SAL (Mercadona) -> [{"code": "848...", "name": "Cacahuete tostado 0% sal"}, ...]
2. FILETE PECHUGA (Mercadona) -> [{"code": "848...", "name": "Pechuga de pollo fileteada"}, ...]
```

### Service: `app/services/enrichment.py`

Orchestrator connecting OFF + Gemini + product updates.

```python
async def enrich_products(
    db: AsyncSession,
    products: list[Product],
    supermarket_hint: str | None = None,
) -> EnrichmentResult
```

Flow:
1. Filter out products that already have `off_synced_at` set (skip them)
2. For each pending product, call `openfoodfacts.search_products(product.name)`
3. Build candidates dict with supermarket context per product
4. Call `gemini.match_products_with_off(candidates, supermarket_name)`
5. For each match: find the full OFF candidate data, update `off_code`, `off_name`, `off_image_url`, `off_categories`
6. Set `off_synced_at = now()` on **all** processed products (match or not)
7. If Gemini fails: do NOT set `off_synced_at` (leaves products for retry)

```python
async def enrich_pending(
    db: AsyncSession,
    limit: int = 10,
) -> EnrichmentResult
```

Flow:
1. Query `products WHERE off_synced_at IS NULL LIMIT {limit}`
2. For each product, get supermarket via join `line_items -> tickets -> supermarkets` (most recent)
3. Build input with per-product supermarket: `"CACAHUETE SIN SAL (Mercadona)"`
4. Same logic: OFF -> Gemini -> update

### Schemas

**`OFFCandidate`** (internal, in `app/schemas/openfoodfacts.py`):
- `code: str`
- `product_name: str`
- `categories: str | None`
- `image_url: str | None`

**`EnrichmentResult`** (response, in `app/schemas/enrichment.py`):
- `processed: int` — total products attempted
- `enriched: int` — matched successfully
- `not_found: int` — no match in OFF/Gemini
- `skipped: int` — already had `off_synced_at`
- `failed: bool` — True if Gemini API failed

**`ProductRead`** (updated):
- Add: `off_code`, `off_name`, `off_image_url`, `off_categories`, `off_synced_at`

## Endpoints

### `POST /api/v1/products/enrich`

- Enriches up to `limit` (query param, default 10) pending products
- Requires Gemini configured (`require_gemini()`)
- Response: `EnrichmentResult` (200 always, even if `failed=True`)

### `POST /api/v1/products/{product_id}/enrich`

- Enriches a single product (forces re-enrichment even if already attempted)
- Requires Gemini configured
- Response: `EnrichmentResult` (processed=1)
- 404 if product not found

### `POST /api/v1/tickets/upload` (modified)

- After `process_extracted_receipt()`, calls `enrich_products()` with new products + supermarket name
- Enrichment failure does NOT affect ticket upload response — ticket is saved regardless
- `ReceiptUploadResponse` adds field: `products_enriched: int`

## Configuration

| Env var | Field | Default | Description |
|---|---|---|---|
| `GEMINI_BATCH_LIMIT` | `gemini_batch_limit` | `0` | 0 = no restriction on Gemini calls |

No new env vars needed — Open Food Facts is a public API without authentication.

## Testing (`tests/test_enrichment.py`)

Mock strategy:
- **Open Food Facts**: mock with `respx` or `httpx` mock (no external network calls)
- **Gemini**: mock the `match_products_with_off` function
- **Database**: real PostgreSQL (project standard)

Test cases:
- `enrich_products` with mocked OFF + Gemini -> product fields updated correctly
- `enrich_products` when Gemini fails -> `off_synced_at` stays NULL
- `enrich_products` when OFF returns no results -> `off_synced_at` set, `off_code` NULL
- `enrich_pending` selects only products with `off_synced_at IS NULL`
- `POST /products/enrich` -> returns `EnrichmentResult`
- `POST /products/{id}/enrich` -> enriches one, 404 if missing
- `POST /tickets/upload` -> enrichment attempted after ticket creation
- Spanish category filtering works correctly
