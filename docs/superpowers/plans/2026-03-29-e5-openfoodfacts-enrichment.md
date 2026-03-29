# E5 — Open Food Facts Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich products extracted from grocery receipts with Open Food Facts data (image, categories, EAN code, canonical name), using Gemini to select the best match from fuzzy search results.

**Architecture:** New `enrichment` orchestrator service calls `openfoodfacts` service (HTTP search) then `gemini` service (match selection). Products gain OFF fields via Alembic migration. Two new endpoints trigger enrichment; ticket upload auto-enriches new products.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (async), httpx (HTTP client for OFF API), google-genai (Gemini), Alembic, pytest + unittest.mock

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `backend/app/models/product.py` | Add OFF fields to Product model |
| Create | `backend/alembic/versions/0002_add_off_fields_to_products.py` | Migration for new columns |
| Modify | `backend/app/schemas/product.py` | Add OFF fields to ProductRead |
| Create | `backend/app/schemas/enrichment.py` | EnrichmentResult + OFFCandidate schemas |
| Create | `backend/app/services/openfoodfacts.py` | OFF API search service |
| Modify | `backend/app/services/gemini.py` | Add match_products_with_off function |
| Create | `backend/app/services/enrichment.py` | Orchestrator: OFF -> Gemini -> update |
| Modify | `backend/app/api/products.py` | Add enrich endpoints |
| Modify | `backend/app/api/tickets.py` | Auto-enrich after ticket upload |
| Modify | `backend/app/schemas/receipt.py` | Add products_enriched to ReceiptUploadResponse |
| Modify | `backend/app/services/receipt.py` | Return new products list for enrichment |
| Create | `backend/tests/test_enrichment.py` | Tests for enrichment flow |

---

### Task 1: Migration and Model — Add OFF fields to products

**Files:**
- Modify: `backend/app/models/product.py`
- Create: `backend/alembic/versions/0002_add_off_fields_to_products.py`
- Modify: `backend/app/schemas/product.py`

- [ ] **Step 1: Add OFF columns to Product model**

```python
# backend/app/models/product.py
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Product(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "products"

    name: Mapped[str] = mapped_column(String(300))
    brand: Mapped[str | None] = mapped_column(String(200))
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id"), index=True
    )

    # Open Food Facts enrichment fields
    off_code: Mapped[str | None] = mapped_column(String(50))
    off_name: Mapped[str | None] = mapped_column(String(300))
    off_image_url: Mapped[str | None] = mapped_column(Text)
    off_categories: Mapped[str | None] = mapped_column(Text)
    off_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    category = relationship("Category", lazy="selectin")
```

- [ ] **Step 2: Create Alembic migration**

```python
# backend/alembic/versions/0002_add_off_fields_to_products.py
"""add OFF fields to products

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-29

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("off_code", sa.String(50), nullable=True))
    op.add_column("products", sa.Column("off_name", sa.String(300), nullable=True))
    op.add_column("products", sa.Column("off_image_url", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("off_categories", sa.Text(), nullable=True))
    op.add_column(
        "products",
        sa.Column("off_synced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("products", "off_synced_at")
    op.drop_column("products", "off_categories")
    op.drop_column("products", "off_image_url")
    op.drop_column("products", "off_name")
    op.drop_column("products", "off_code")
```

- [ ] **Step 3: Update ProductRead schema**

Add OFF fields to `backend/app/schemas/product.py`. The `ProductRead` class becomes:

```python
class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    brand: str | None
    category_id: uuid.UUID | None
    off_code: str | None
    off_name: str | None
    off_image_url: str | None
    off_categories: str | None
    off_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 4: Verify migration applies and existing tests pass**

Run: `docker compose down -v && docker compose up --build -d`

Then: `docker compose exec api pytest tests/test_products.py tests/test_health.py -v`

Expected: All tests PASS. ProductRead responses now include `off_*` fields as `null`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/product.py backend/alembic/versions/0002_add_off_fields_to_products.py backend/app/schemas/product.py
git commit -m "feat(e5): add Open Food Facts fields to products model and schema"
```

---

### Task 2: Schemas — EnrichmentResult and OFFCandidate

**Files:**
- Create: `backend/app/schemas/enrichment.py`

- [ ] **Step 1: Create enrichment schemas**

```python
# backend/app/schemas/enrichment.py
from pydantic import BaseModel


class OFFCandidate(BaseModel):
    """A product candidate returned by Open Food Facts search."""

    code: str
    product_name: str
    categories: str | None = None
    image_url: str | None = None


class EnrichmentResult(BaseModel):
    """Response from product enrichment operations."""

    processed: int
    enriched: int
    not_found: int
    skipped: int
    failed: bool = False
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/enrichment.py
git commit -m "feat(e5): add enrichment schemas (OFFCandidate, EnrichmentResult)"
```

---

### Task 3: Open Food Facts service

**Files:**
- Create: `backend/app/services/openfoodfacts.py`
- Create: `backend/tests/test_enrichment.py` (OFF search tests)

- [ ] **Step 1: Write failing tests for OFF search**

```python
# backend/tests/test_enrichment.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.schemas.enrichment import OFFCandidate
from app.services.openfoodfacts import search_products


@pytest.fixture(autouse=True)
def _fake_api_key():
    original = settings.gemini_api_key
    settings.gemini_api_key = "fake-key-for-tests"
    yield
    settings.gemini_api_key = original


def _off_api_response(products: list[dict]) -> dict:
    """Build a mock OFF API JSON response."""
    return {"count": len(products), "products": products}


def _off_product(
    code: str = "8480000340313",
    product_name: str = "Cacahuete tostado 0% sal",
    categories: str = "Cacahuetes,en:Peanuts,pt:Amendoins",
    image_url: str = "https://images.openfoodfacts.org/example.jpg",
    stores: str = "Mercadona",
) -> dict:
    return {
        "code": code,
        "product_name": product_name,
        "categories": categories,
        "image_url": image_url,
        "stores": stores,
    }


class TestSearchProducts:
    @patch("app.services.openfoodfacts.httpx.AsyncClient")
    async def test_returns_candidates(self, mock_client_cls: MagicMock):
        mock_response = MagicMock()
        mock_response.json.return_value = _off_api_response([_off_product()])
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await search_products("cacahuete sin sal")

        assert len(result) == 1
        assert isinstance(result[0], OFFCandidate)
        assert result[0].code == "8480000340313"
        assert result[0].product_name == "Cacahuete tostado 0% sal"

    @patch("app.services.openfoodfacts.httpx.AsyncClient")
    async def test_filters_non_spanish_categories(self, mock_client_cls: MagicMock):
        mock_response = MagicMock()
        mock_response.json.return_value = _off_api_response(
            [_off_product(categories="Cacahuetes,Frutos secos,en:Peanuts,pt:Amendoins,fr:Arachides")]
        )
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await search_products("cacahuete")

        assert result[0].categories == "Cacahuetes,Frutos secos"

    @patch("app.services.openfoodfacts.httpx.AsyncClient")
    async def test_returns_empty_on_api_error(self, mock_client_cls: MagicMock):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await search_products("cacahuete")

        assert result == []

    @patch("app.services.openfoodfacts.httpx.AsyncClient")
    async def test_returns_empty_when_no_products(self, mock_client_cls: MagicMock):
        mock_response = MagicMock()
        mock_response.json.return_value = _off_api_response([])
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await search_products("xyznonexistent")

        assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api pytest tests/test_enrichment.py::TestSearchProducts -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.openfoodfacts'`

- [ ] **Step 3: Implement OFF search service**

```python
# backend/app/services/openfoodfacts.py
import logging
import re

import httpx

from app.schemas.enrichment import OFFCandidate

logger = logging.getLogger(__name__)

OFF_SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"
OFF_FIELDS = "code,product_name,categories,image_url,stores"
_NON_SPANISH_PREFIX_RE = re.compile(r"^[a-z]{2}:")


def _filter_spanish_categories(categories: str | None) -> str | None:
    """Keep only categories that don't have a language prefix (assumed Spanish)."""
    if not categories:
        return None
    parts = [c.strip() for c in categories.split(",")]
    spanish = [p for p in parts if not _NON_SPANISH_PREFIX_RE.match(p)]
    return ",".join(spanish) if spanish else None


async def search_products(product_name: str, max_results: int = 4) -> list[OFFCandidate]:
    """Search Open Food Facts for product candidates. Returns empty list on any error."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                OFF_SEARCH_URL,
                params={
                    "search_terms": product_name,
                    "search_simple": 1,
                    "action": "process",
                    "json": 1,
                    "page_size": max_results,
                    "fields": OFF_FIELDS,
                },
            )
            response.raise_for_status()
    except Exception:
        logger.warning("Open Food Facts API error for '%s'", product_name, exc_info=True)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec api pytest tests/test_enrichment.py::TestSearchProducts -v`

Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/openfoodfacts.py backend/tests/test_enrichment.py
git commit -m "feat(e5): add Open Food Facts search service with tests"
```

---

### Task 4: Gemini matching function

**Files:**
- Modify: `backend/app/services/gemini.py`
- Modify: `backend/tests/test_enrichment.py` (add Gemini matching tests)

- [ ] **Step 1: Write failing tests for Gemini matching**

Append to `backend/tests/test_enrichment.py`:

```python
from app.services.gemini import match_products_with_off


class TestMatchProductsWithOff:
    @patch("app.services.gemini._get_client")
    async def test_returns_matched_codes(self, mock_get_client: MagicMock):
        mock_response = MagicMock()
        mock_response.text = '{"CACAHUETE SIN SAL": "8480000340313", "FILETE PECHUGA": null}'
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        candidates = {
            "CACAHUETE SIN SAL": [
                OFFCandidate(
                    code="8480000340313",
                    product_name="Cacahuete tostado 0% sal",
                    categories="Cacahuetes",
                    image_url="https://example.com/img.jpg",
                ),
            ],
            "FILETE PECHUGA": [
                OFFCandidate(
                    code="8480000999999",
                    product_name="Filete de ternera",
                    categories="Carnes",
                    image_url=None,
                ),
            ],
        }

        result = await match_products_with_off(candidates, supermarket_name="MERCADONA")

        assert result["CACAHUETE SIN SAL"] == "8480000340313"
        assert result["FILETE PECHUGA"] is None

    @patch("app.services.gemini._get_client")
    async def test_returns_empty_on_gemini_error(self, mock_get_client: MagicMock):
        from google.genai.errors import APIError as GeminiAPIError

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=GeminiAPIError(code=429, response_json={})
        )
        mock_get_client.return_value = mock_client

        candidates = {
            "CACAHUETE SIN SAL": [
                OFFCandidate(
                    code="8480000340313",
                    product_name="Cacahuete tostado 0% sal",
                ),
            ],
        }

        result = await match_products_with_off(candidates, supermarket_name="MERCADONA")

        assert result == {}

    @patch("app.services.gemini._get_client")
    async def test_handles_empty_candidates(self, mock_get_client: MagicMock):
        result = await match_products_with_off({})

        assert result == {}
        mock_get_client.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api pytest tests/test_enrichment.py::TestMatchProductsWithOff -v`

Expected: FAIL — `ImportError: cannot import name 'match_products_with_off'`

- [ ] **Step 3: Implement Gemini matching function**

Add to the end of `backend/app/services/gemini.py`:

```python
import json

from app.schemas.enrichment import OFFCandidate

MATCHING_PROMPT_TEMPLATE = (
    "You are matching abbreviated Spanish supermarket receipt product names "
    "to Open Food Facts product entries.\n\n"
    "For each product below, choose the BEST matching Open Food Facts candidate "
    "or respond with null if none is a good match.\n"
    "{supermarket_hint}\n"
    "Respond ONLY with a JSON object mapping each product name to the chosen "
    "EAN code (string) or null. Example: "
    '{{"LECHE ENTERA": "8480000123456", "UNKNOWN PRODUCT": null}}\n\n'
    "Products:\n{products_block}"
)


async def match_products_with_off(
    candidates: dict[str, list[OFFCandidate]],
    supermarket_name: str | None = None,
) -> dict[str, str | None]:
    """Use Gemini to select the best OFF match for each product. Returns empty dict on error."""
    if not candidates:
        return {}

    supermarket_hint = ""
    if supermarket_name:
        supermarket_hint = (
            f"These products were purchased at {supermarket_name}. "
            "Consider this when choosing (e.g., Mercadona sells Hacendado brand)."
        )

    lines = []
    for i, (name, options) in enumerate(candidates.items(), 1):
        options_str = ", ".join(
            f'{{"code": "{o.code}", "name": "{o.product_name}"}}'
            for o in options
        )
        lines.append(f"{i}. {name} -> [{options_str}]")

    products_block = "\n".join(lines)
    prompt = MATCHING_PROMPT_TEMPLATE.format(
        supermarket_hint=supermarket_hint, products_block=products_block
    )

    try:
        client = _get_client()
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        return json.loads(response.text)
    except GeminiAPIError:
        logger.warning("Gemini API error during OFF matching", exc_info=True)
        return {}
    except (json.JSONDecodeError, ValueError):
        logger.error("Failed to parse Gemini matching response: %s", response.text)
        return {}
```

Also add the missing import at the top of the file — add `GeminiAPIError` import. The import block becomes:

```python
import json
import logging
import re

from google import genai
from google.genai import types
from google.genai.errors import APIError as GeminiAPIError
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.enrichment import OFFCandidate
from app.schemas.receipt import ExtractedReceipt
```

And remove the bare `except` around Gemini call in `extract_receipt_from_pdf` — it already lets `GeminiAPIError` propagate to the router, so no change needed there.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec api pytest tests/test_enrichment.py::TestMatchProductsWithOff -v`

Expected: All 3 tests PASS.

- [ ] **Step 5: Run all existing tests to check for regressions**

Run: `docker compose exec api pytest -v`

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/gemini.py backend/tests/test_enrichment.py
git commit -m "feat(e5): add Gemini product matching function for OFF candidates"
```

---

### Task 5: Enrichment orchestrator service

**Files:**
- Create: `backend/app/services/enrichment.py`
- Modify: `backend/tests/test_enrichment.py` (add orchestrator tests)

- [ ] **Step 1: Write failing tests for enrich_products**

Append to `backend/tests/test_enrichment.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.supermarket import Supermarket
from app.models.ticket import Ticket
from app.models.line_item import LineItem
from app.services.enrichment import enrich_products, enrich_pending

import datetime
from decimal import Decimal


async def _create_product(db: AsyncSession, name: str = "CACAHUETE SIN SAL") -> Product:
    product = Product(name=name)
    db.add(product)
    await db.flush()
    return product


async def _create_product_with_ticket(
    db: AsyncSession,
    product_name: str = "CACAHUETE SIN SAL",
    supermarket_name: str = "MERCADONA",
) -> Product:
    """Create a product linked to a ticket via a line item, for enrich_pending tests."""
    supermarket = Supermarket(name=supermarket_name)
    db.add(supermarket)
    await db.flush()

    ticket = Ticket(
        date=datetime.date(2026, 3, 21),
        supermarket_id=supermarket.id,
        total=Decimal("10.00"),
    )
    db.add(ticket)
    await db.flush()

    product = Product(name=product_name)
    db.add(product)
    await db.flush()

    line_item = LineItem(
        ticket_id=ticket.id,
        product_id=product.id,
        quantity=Decimal("1"),
        unit_price=Decimal("2.50"),
        line_total=Decimal("2.50"),
    )
    db.add(line_item)
    await db.flush()
    return product


class TestEnrichProducts:
    @patch("app.services.enrichment.match_products_with_off", new_callable=AsyncMock)
    @patch("app.services.enrichment.search_products", new_callable=AsyncMock)
    async def test_enriches_product_successfully(
        self, mock_search: AsyncMock, mock_match: AsyncMock, db_session: AsyncSession
    ):
        product = await _create_product(db_session)

        mock_search.return_value = [
            OFFCandidate(
                code="8480000340313",
                product_name="Cacahuete tostado 0% sal",
                categories="Cacahuetes,Frutos secos",
                image_url="https://images.openfoodfacts.org/example.jpg",
            ),
        ]
        mock_match.return_value = {"CACAHUETE SIN SAL": "8480000340313"}

        result = await enrich_products(db_session, [product], supermarket_hint="MERCADONA")

        assert result.processed == 1
        assert result.enriched == 1
        assert result.not_found == 0
        assert result.failed is False
        assert product.off_code == "8480000340313"
        assert product.off_name == "Cacahuete tostado 0% sal"
        assert product.off_image_url == "https://images.openfoodfacts.org/example.jpg"
        assert product.off_categories == "Cacahuetes,Frutos secos"
        assert product.off_synced_at is not None

    @patch("app.services.enrichment.match_products_with_off", new_callable=AsyncMock)
    @patch("app.services.enrichment.search_products", new_callable=AsyncMock)
    async def test_sets_synced_at_when_no_match(
        self, mock_search: AsyncMock, mock_match: AsyncMock, db_session: AsyncSession
    ):
        product = await _create_product(db_session)

        mock_search.return_value = [
            OFFCandidate(code="999", product_name="Unrelated product"),
        ]
        mock_match.return_value = {"CACAHUETE SIN SAL": None}

        result = await enrich_products(db_session, [product])

        assert result.processed == 1
        assert result.enriched == 0
        assert result.not_found == 1
        assert product.off_code is None
        assert product.off_synced_at is not None

    @patch("app.services.enrichment.match_products_with_off", new_callable=AsyncMock)
    @patch("app.services.enrichment.search_products", new_callable=AsyncMock)
    async def test_skips_already_synced_products(
        self, mock_search: AsyncMock, mock_match: AsyncMock, db_session: AsyncSession
    ):
        product = await _create_product(db_session)
        product.off_synced_at = datetime.datetime.now(datetime.UTC)
        await db_session.flush()

        result = await enrich_products(db_session, [product])

        assert result.processed == 0
        assert result.skipped == 1
        mock_search.assert_not_called()

    @patch("app.services.enrichment.match_products_with_off", new_callable=AsyncMock)
    @patch("app.services.enrichment.search_products", new_callable=AsyncMock)
    async def test_gemini_failure_leaves_synced_at_null(
        self, mock_search: AsyncMock, mock_match: AsyncMock, db_session: AsyncSession
    ):
        product = await _create_product(db_session)

        mock_search.return_value = [
            OFFCandidate(code="8480000340313", product_name="Cacahuete"),
        ]
        mock_match.return_value = {}  # Gemini failed

        result = await enrich_products(db_session, [product])

        assert result.failed is True
        assert product.off_synced_at is None

    @patch("app.services.enrichment.match_products_with_off", new_callable=AsyncMock)
    @patch("app.services.enrichment.search_products", new_callable=AsyncMock)
    async def test_no_off_results_sets_synced_at(
        self, mock_search: AsyncMock, mock_match: AsyncMock, db_session: AsyncSession
    ):
        product = await _create_product(db_session)
        mock_search.return_value = []  # OFF returned nothing

        result = await enrich_products(db_session, [product])

        assert result.processed == 1
        assert result.enriched == 0
        assert result.not_found == 1
        assert product.off_synced_at is not None
        mock_match.assert_not_called()  # No candidates = no Gemini call


class TestEnrichPending:
    @patch("app.services.enrichment.match_products_with_off", new_callable=AsyncMock)
    @patch("app.services.enrichment.search_products", new_callable=AsyncMock)
    async def test_selects_unsynced_products(
        self, mock_search: AsyncMock, mock_match: AsyncMock, db_session: AsyncSession
    ):
        product = await _create_product_with_ticket(db_session)

        mock_search.return_value = [
            OFFCandidate(
                code="8480000340313",
                product_name="Cacahuete tostado 0% sal",
                categories="Cacahuetes",
                image_url="https://example.com/img.jpg",
            ),
        ]
        mock_match.return_value = {"CACAHUETE SIN SAL": "8480000340313"}

        result = await enrich_pending(db_session, limit=10)

        assert result.processed == 1
        assert result.enriched == 1
        assert product.off_code == "8480000340313"

    @patch("app.services.enrichment.match_products_with_off", new_callable=AsyncMock)
    @patch("app.services.enrichment.search_products", new_callable=AsyncMock)
    async def test_passes_supermarket_name_to_gemini(
        self, mock_search: AsyncMock, mock_match: AsyncMock, db_session: AsyncSession
    ):
        await _create_product_with_ticket(
            db_session, product_name="LECHE ENTERA", supermarket_name="MERCADONA"
        )

        mock_search.return_value = [
            OFFCandidate(code="848", product_name="Leche entera"),
        ]
        mock_match.return_value = {"LECHE ENTERA": "848"}

        await enrich_pending(db_session, limit=10)

        # Verify supermarket was included in the candidates dict key
        call_args = mock_match.call_args
        candidates = call_args[0][0] if call_args[0] else call_args[1]["candidates"]
        assert "LECHE ENTERA (MERCADONA)" in candidates
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api pytest tests/test_enrichment.py::TestEnrichProducts -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.enrichment'`

- [ ] **Step 3: Implement enrichment orchestrator**

```python
# backend/app/services/enrichment.py
import datetime
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.line_item import LineItem
from app.models.product import Product
from app.models.ticket import Ticket
from app.schemas.enrichment import EnrichmentResult, OFFCandidate
from app.services.gemini import match_products_with_off
from app.services.openfoodfacts import search_products

logger = logging.getLogger(__name__)


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

    # Step 1: Search OFF for each product
    all_candidates: dict[str, list[OFFCandidate]] = {}
    for product in pending:
        candidates = await search_products(product.name)
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
    candidates_flat = {
        c.code: c for candidates in all_candidates.values() for c in candidates
    }

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
            product.off_categories = off.categories
            enriched += 1

        if not failed:
            product.off_synced_at = now

    await db.flush()
    not_found = len(pending) - enriched - len(products_without_candidates)

    return EnrichmentResult(
        processed=len(pending),
        enriched=enriched,
        not_found=not_found + len(products_without_candidates),
        skipped=skipped,
        failed=failed,
    )


async def enrich_pending(
    db: AsyncSession,
    limit: int = 10,
) -> EnrichmentResult:
    """Enrich up to `limit` products that haven't been synced yet."""
    result = await db.execute(
        select(Product).where(Product.off_synced_at.is_(None)).limit(limit)
    )
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
            from app.models.supermarket import Supermarket

            supermarket = await db.get(Supermarket, supermarket_id)
            product_supermarkets[product.name] = supermarket.name if supermarket else None
        else:
            product_supermarkets[product.name] = None

    # Build candidates with per-product supermarket context
    all_candidates: dict[str, list[OFFCandidate]] = {}
    pending_with_candidates: list[Product] = []
    now = datetime.datetime.now(datetime.UTC)

    for product in products:
        candidates = await search_products(product.name)
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
            product.off_categories = off.categories
            enriched += 1

        if not failed:
            product.off_synced_at = now

    await db.flush()
    no_candidates_count = len(products) - len(pending_with_candidates)

    return EnrichmentResult(
        processed=len(products),
        enriched=enriched,
        not_found=len(products) - enriched - no_candidates_count + no_candidates_count,
        skipped=0,
        failed=failed,
    )
```

Wait — `not_found` calculation is cleaner as: `not_found = len(products) - enriched`. Simplify the last line:

```python
    return EnrichmentResult(
        processed=len(products),
        enriched=enriched,
        not_found=len(products) - enriched,
        skipped=0,
        failed=failed,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec api pytest tests/test_enrichment.py::TestEnrichProducts tests/test_enrichment.py::TestEnrichPending -v`

Expected: All tests PASS.

- [ ] **Step 5: Run full test suite**

Run: `docker compose exec api pytest -v`

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/enrichment.py backend/tests/test_enrichment.py
git commit -m "feat(e5): add enrichment orchestrator service with tests"
```

---

### Task 6: Enrich endpoints on products router

**Files:**
- Modify: `backend/app/api/products.py`
- Modify: `backend/tests/test_enrichment.py` (add endpoint tests)

- [ ] **Step 1: Write failing tests for enrich endpoints**

Append to `backend/tests/test_enrichment.py`:

```python
from httpx import AsyncClient
from app.core.config import settings

PRODUCTS_BASE = "/api/v1/products"


class TestEnrichEndpoints:
    @patch("app.api.products.enrich_pending", new_callable=AsyncMock)
    async def test_batch_enrich(self, mock_enrich: AsyncMock, client: AsyncClient):
        from app.schemas.enrichment import EnrichmentResult

        mock_enrich.return_value = EnrichmentResult(
            processed=2, enriched=1, not_found=1, skipped=0
        )

        resp = await client.post(f"{PRODUCTS_BASE}/enrich?limit=10")

        assert resp.status_code == 200
        body = resp.json()
        assert body["processed"] == 2
        assert body["enriched"] == 1
        assert body["not_found"] == 1

    @patch("app.api.products.enrich_products", new_callable=AsyncMock)
    async def test_single_enrich(
        self, mock_enrich: AsyncMock, client: AsyncClient, db_session: AsyncSession
    ):
        from app.schemas.enrichment import EnrichmentResult

        product = await _create_product(db_session)
        mock_enrich.return_value = EnrichmentResult(
            processed=1, enriched=1, not_found=0, skipped=0
        )

        resp = await client.post(f"{PRODUCTS_BASE}/{product.id}/enrich")

        assert resp.status_code == 200
        assert resp.json()["processed"] == 1

    async def test_single_enrich_404(self, client: AsyncClient):
        import uuid

        resp = await client.post(f"{PRODUCTS_BASE}/{uuid.uuid4()}/enrich")
        assert resp.status_code == 404

    async def test_batch_enrich_requires_gemini(self, client: AsyncClient):
        settings.gemini_api_key = ""
        resp = await client.post(f"{PRODUCTS_BASE}/enrich")
        assert resp.status_code == 503
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api pytest tests/test_enrichment.py::TestEnrichEndpoints -v`

Expected: FAIL — 404 (routes don't exist yet).

- [ ] **Step 3: Add enrich endpoints to products router**

Modify `backend/app/api/products.py` to add the imports and two new endpoints. The new endpoints MUST be placed **before** the `/{product_id}` routes to avoid path conflicts:

```python
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_gemini
from app.api.exceptions import conflict, not_found
from app.core.database import get_db
from app.schemas.enrichment import EnrichmentResult
from app.schemas.pagination import PaginatedResponse
from app.schemas.product import ProductCreate, ProductRead, ProductUpdate
from app.services import product as product_service
from app.services.enrichment import enrich_pending, enrich_products

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


@router.post("/enrich", response_model=EnrichmentResult)
async def batch_enrich_products(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_gemini),
):
    return await enrich_pending(db, limit=limit)


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec api pytest tests/test_enrichment.py::TestEnrichEndpoints -v`

Expected: All 4 tests PASS.

- [ ] **Step 5: Run full test suite**

Run: `docker compose exec api pytest -v`

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/products.py backend/tests/test_enrichment.py
git commit -m "feat(e5): add product enrichment endpoints (batch + single)"
```

---

### Task 7: Auto-enrich after ticket upload

**Files:**
- Modify: `backend/app/services/receipt.py`
- Modify: `backend/app/schemas/receipt.py`
- Modify: `backend/app/api/tickets.py`
- Modify: `backend/tests/test_enrichment.py` (add ticket upload enrichment test)

- [ ] **Step 1: Write failing test for auto-enrichment on upload**

Append to `backend/tests/test_enrichment.py`:

```python
from tests.conftest import make_extracted_receipt, unique_pdf

TICKETS_BASE = "/api/v1/tickets"


def _pdf_upload(content: bytes | None = None):
    return {"file": ("ticket.pdf", content or unique_pdf(), "application/pdf")}


class TestTicketUploadEnrichment:
    @patch("app.api.tickets.extract_receipt_from_pdf", new_callable=AsyncMock)
    @patch("app.services.receipt.enrich_products", new_callable=AsyncMock)
    async def test_upload_triggers_enrichment(
        self,
        mock_enrich: AsyncMock,
        mock_extract: AsyncMock,
        client: AsyncClient,
    ):
        from app.schemas.enrichment import EnrichmentResult

        mock_extract.return_value = make_extracted_receipt()
        mock_enrich.return_value = EnrichmentResult(
            processed=1, enriched=1, not_found=0, skipped=0
        )

        resp = await client.post(f"{TICKETS_BASE}/upload", files=_pdf_upload())

        assert resp.status_code == 200
        body = resp.json()
        assert body["products_enriched"] == 1
        mock_enrich.assert_called_once()

    @patch("app.api.tickets.extract_receipt_from_pdf", new_callable=AsyncMock)
    @patch("app.services.receipt.enrich_products", new_callable=AsyncMock)
    async def test_upload_succeeds_when_enrichment_fails(
        self,
        mock_enrich: AsyncMock,
        mock_extract: AsyncMock,
        client: AsyncClient,
    ):
        mock_extract.return_value = make_extracted_receipt()
        mock_enrich.side_effect = Exception("Gemini down")

        resp = await client.post(f"{TICKETS_BASE}/upload", files=_pdf_upload())

        assert resp.status_code == 200
        body = resp.json()
        assert body["products_enriched"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api pytest tests/test_enrichment.py::TestTicketUploadEnrichment -v`

Expected: FAIL — `products_enriched` not in response.

- [ ] **Step 3: Add products_enriched to ReceiptUploadResponse**

In `backend/app/schemas/receipt.py`, add the field to `ReceiptUploadResponse`:

```python
class ReceiptUploadResponse(BaseModel):
    """Response after processing a receipt PDF."""

    ticket_id: UUID
    supermarket: str = Field(examples=["MERCADONA"])
    date: datetime.date = Field(examples=["2026-03-21"])
    total: Decimal = Field(examples=["62.00"])
    products_created: int = Field(examples=[26])
    products_matched: int = Field(examples=[0])
    line_items_count: int = Field(examples=[26])
    products_enriched: int = Field(default=0, examples=[5])
    duplicate: bool = False

    @staticmethod
    def duplicate_from(ticket: "Ticket") -> "ReceiptUploadResponse":
        return ReceiptUploadResponse(
            ticket_id=ticket.id,
            supermarket=ticket.supermarket.name,
            date=ticket.date,
            total=ticket.total,
            products_created=0,
            products_matched=0,
            line_items_count=0,
            duplicate=True,
        )
```

- [ ] **Step 4: Modify receipt service to return new products and call enrichment**

In `backend/app/services/receipt.py`, modify `process_extracted_receipt` to call enrichment. Add the import and the enrichment call after line items are created:

Add import at top:

```python
from app.services.enrichment import enrich_products
```

Modify the end of `process_extracted_receipt` (after the line items loop, replace the existing `logger.info` and `return` block):

```python
    # Collect newly created products for enrichment
    new_products = [
        products_map[name]
        for name in dict.fromkeys(product_names)
        if products_map[name].off_synced_at is None
    ]

    products_enriched = 0
    if new_products:
        try:
            enrichment_result = await enrich_products(
                db, new_products, supermarket_hint=data.supermarket_name
            )
            products_enriched = enrichment_result.enriched
        except Exception:
            logger.warning("Enrichment failed for ticket %s, continuing", ticket.id, exc_info=True)

    logger.info(
        "Ticket %s saved: %d new products, %d matched, %d line items, %d enriched",
        ticket.id,
        products_created,
        products_matched,
        len(data.line_items),
        products_enriched,
    )
    return ReceiptUploadResponse(
        ticket_id=ticket.id,
        supermarket=supermarket.name,
        date=ticket.date,
        total=ticket.total,
        products_created=products_created,
        products_matched=products_matched,
        line_items_count=len(data.line_items),
        products_enriched=products_enriched,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec api pytest tests/test_enrichment.py::TestTicketUploadEnrichment -v`

Expected: All 2 tests PASS.

- [ ] **Step 6: Run full test suite to check regressions**

Run: `docker compose exec api pytest -v`

Expected: All tests PASS. Existing receipt tests will now show `products_enriched: 0` in responses (since enrichment is mocked/not triggered in those tests).

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/receipt.py backend/app/services/receipt.py backend/tests/test_enrichment.py
git commit -m "feat(e5): auto-enrich products after ticket upload"
```

---

### Task 8: Final integration test and cleanup

**Files:**
- Modify: `backend/tests/test_enrichment.py` (verify full test organization)

- [ ] **Step 1: Run full test suite**

Run: `docker compose exec api pytest -v`

Expected: All tests PASS.

- [ ] **Step 2: Run linter**

Run: `docker compose exec api ruff check app/ tests/`

Expected: No errors.

- [ ] **Step 3: Run formatter**

Run: `docker compose exec api ruff format app/ tests/`

Expected: No changes (or auto-formatted).

- [ ] **Step 4: Commit any formatting fixes**

```bash
git add -A
git commit -m "chore(e5): lint and format fixes"
```

(Skip this commit if there are no changes.)

- [ ] **Step 5: Stop docker**

```bash
docker compose down
```
