import datetime
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.category import Category
from app.models.line_item import LineItem
from app.models.product import Product
from app.models.supermarket import Supermarket
from app.models.ticket import Ticket
from app.schemas.enrichment import EnrichmentResult, OFFCandidate
from app.services.enrichment import enrich_pending, enrich_products, reset_failed_enrichments
from app.services.gemini import match_products_with_off
from app.services.openfoodfacts import _simplify_search_terms, search_products
from tests.conftest import make_extracted_receipt, unique_pdf


@pytest.fixture(autouse=True)
def _fake_api_key():
    original = settings.gemini_api_key
    settings.gemini_api_key = "fake-key-for-tests"
    yield
    settings.gemini_api_key = original


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


PRODUCTS_BASE = "/api/v1/products"
TICKETS_BASE = "/api/v1/tickets"


def _pdf_upload(content: bytes | None = None):
    return {"file": ("ticket.pdf", content or unique_pdf(), "application/pdf")}


# ---------------------------------------------------------------------------
# Name simplification tests
# ---------------------------------------------------------------------------


class TestSimplifySearchTerms:
    def test_removes_quantities(self):
        assert _simplify_search_terms("LECHE ENTERA 1L") == "leche entera"

    def test_removes_percentages(self):
        assert _simplify_search_terms("CACAHUETE TOSTADO 0% SAL") == "cacahuete tostado sal"

    def test_truncates_to_three_words(self):
        assert _simplify_search_terms("FILETE PECHUGA POLLO CAMPERO") == "filete pechuga pollo"

    def test_returns_none_when_no_change(self):
        assert _simplify_search_terms("leche") is None

    def test_returns_none_for_empty(self):
        assert _simplify_search_terms("") is None

    def test_removes_standalone_numbers(self):
        assert _simplify_search_terms("PAN BIMBO 12 REBANADAS") == "pan bimbo rebanadas"

    def test_removes_weight_with_decimals(self):
        assert _simplify_search_terms("JAMON SERRANO 0,5 KG") == "jamon serrano"

    def test_returns_none_for_short_result(self):
        assert _simplify_search_terms("1L") is None


# ---------------------------------------------------------------------------
# Open Food Facts search tests
# ---------------------------------------------------------------------------


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
        cats = "Cacahuetes,Frutos secos,en:Peanuts,pt:Amendoins,fr:Arachides"
        mock_response.json.return_value = _off_api_response([_off_product(categories=cats)])
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

    @patch("app.services.openfoodfacts.httpx.AsyncClient")
    async def test_falls_back_to_simplified_search(self, mock_client_cls: MagicMock):
        empty_response = MagicMock()
        empty_response.json.return_value = _off_api_response([])
        empty_response.raise_for_status = MagicMock()
        empty_response.status_code = 200

        full_response = MagicMock()
        full_response.json.return_value = _off_api_response([_off_product()])
        full_response.raise_for_status = MagicMock()
        full_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[empty_response, full_response])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await search_products("CACAHUETE TOSTADO 0% SAL 200G")

        assert len(result) == 1
        assert mock_client.get.call_count == 2

    async def test_uses_provided_client(self):
        mock_response = MagicMock()
        mock_response.json.return_value = _off_api_response([_off_product()])
        mock_response.raise_for_status = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await search_products("cacahuete", client=mock_client)

        assert len(result) == 1
        mock_client.get.assert_called_once()


# ---------------------------------------------------------------------------
# Gemini matching tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Enrichment orchestrator tests
# ---------------------------------------------------------------------------


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
        mock_match.return_value = {"CACAHUETE SIN SAL (MERCADONA)": "8480000340313"}

        result = await enrich_products(db_session, [product], supermarket_hint="MERCADONA")

        assert result.processed == 1
        assert result.enriched == 1
        assert result.not_found == 0
        assert result.failed is False
        assert product.off_code == "8480000340313"
        assert product.off_name == "Cacahuete tostado 0% sal"
        assert product.off_image_url == "https://images.openfoodfacts.org/example.jpg"
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

    @patch("app.services.enrichment.match_products_with_off", new_callable=AsyncMock)
    @patch("app.services.enrichment.search_products", new_callable=AsyncMock)
    async def test_assigns_categories_from_off(
        self, mock_search: AsyncMock, mock_match: AsyncMock, db_session: AsyncSession
    ):
        product = await _create_product(db_session)

        mock_search.return_value = [
            OFFCandidate(
                code="8480000340313",
                product_name="Cacahuete tostado 0% sal",
                categories="Cacahuetes,Frutos secos",
                image_url="https://example.com/img.jpg",
            ),
        ]
        mock_match.return_value = {"CACAHUETE SIN SAL": "8480000340313"}

        await enrich_products(db_session, [product])

        # Verify categories were created in the database
        result = await db_session.execute(select(Category).order_by(Category.name))
        cats = result.scalars().all()
        assert len(cats) == 2
        cat_names = {c.name for c in cats}
        assert cat_names == {"Cacahuetes", "Frutos secos"}

        # Verify product is linked to both categories
        await db_session.refresh(product)
        product_cat_names = {c.name for c in product.categories}
        assert product_cat_names == {"Cacahuetes", "Frutos secos"}

    @patch("app.services.enrichment.match_products_with_off", new_callable=AsyncMock)
    @patch("app.services.enrichment.search_products", new_callable=AsyncMock)
    async def test_reuses_existing_categories(
        self, mock_search: AsyncMock, mock_match: AsyncMock, db_session: AsyncSession
    ):
        # Pre-create one category
        existing_cat = Category(name="Cacahuetes")
        db_session.add(existing_cat)
        await db_session.flush()

        product = await _create_product(db_session)

        mock_search.return_value = [
            OFFCandidate(
                code="8480000340313",
                product_name="Cacahuete tostado 0% sal",
                categories="Cacahuetes,Frutos secos",
            ),
        ]
        mock_match.return_value = {"CACAHUETE SIN SAL": "8480000340313"}

        await enrich_products(db_session, [product])

        # Should have 2 categories total, not 3
        result = await db_session.execute(select(Category))
        all_cats = result.scalars().all()
        assert len(all_cats) == 2

        # The existing category should be the same object
        await db_session.refresh(product)
        assert any(c.id == existing_cat.id for c in product.categories)


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
        mock_match.return_value = {"CACAHUETE SIN SAL (MERCADONA)": "8480000340313"}

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
        mock_match.return_value = {"LECHE ENTERA (MERCADONA)": "848"}

        await enrich_pending(db_session, limit=10)

        # Verify supermarket was included in the candidates dict key
        call_args = mock_match.call_args
        candidates = call_args[0][0] if call_args[0] else call_args[1]["candidates"]
        assert "LECHE ENTERA (MERCADONA)" in candidates


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


class TestEnrichEndpoints:
    @patch("app.api.products.enrich_pending", new_callable=AsyncMock)
    async def test_batch_enrich(self, mock_enrich: AsyncMock, client: AsyncClient):
        mock_enrich.return_value = EnrichmentResult(processed=2, enriched=1, not_found=1, skipped=0)

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
        product = await _create_product(db_session)
        mock_enrich.return_value = EnrichmentResult(processed=1, enriched=1, not_found=0, skipped=0)

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


# ---------------------------------------------------------------------------
# Ticket upload enrichment tests
# ---------------------------------------------------------------------------


class TestTicketUploadEnrichment:
    @patch("app.api.tickets.extract_receipt_from_pdf", new_callable=AsyncMock)
    @patch("app.services.receipt.enrich_products", new_callable=AsyncMock)
    async def test_upload_triggers_enrichment(
        self,
        mock_enrich: AsyncMock,
        mock_extract: AsyncMock,
        client: AsyncClient,
    ):
        mock_extract.return_value = make_extracted_receipt()
        mock_enrich.return_value = EnrichmentResult(processed=1, enriched=1, not_found=0, skipped=0)

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


# ---------------------------------------------------------------------------
# Manual product-category endpoints
# ---------------------------------------------------------------------------


class TestProductCategoryEndpoints:
    async def test_add_category_to_product(self, client: AsyncClient, db_session: AsyncSession):
        product = await _create_product(db_session)
        cat = Category(name="Cacahuetes")
        db_session.add(cat)
        await db_session.flush()
        await db_session.commit()

        resp = await client.post(
            f"{PRODUCTS_BASE}/{product.id}/categories",
            json={"category_id": str(cat.id)},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["categories"]) == 1
        assert body["categories"][0]["name"] == "Cacahuetes"

    async def test_add_category_duplicate(self, client: AsyncClient, db_session: AsyncSession):
        product = await _create_product(db_session)
        cat = Category(name="Cacahuetes")
        db_session.add(cat)
        await db_session.flush()
        await db_session.refresh(product, ["categories"])
        product.categories.append(cat)
        await db_session.flush()
        await db_session.commit()

        resp = await client.post(
            f"{PRODUCTS_BASE}/{product.id}/categories",
            json={"category_id": str(cat.id)},
        )

        assert resp.status_code == 409

    async def test_add_category_product_not_found(self, client: AsyncClient):
        resp = await client.post(
            f"{PRODUCTS_BASE}/{uuid.uuid4()}/categories",
            json={"category_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 404

    async def test_add_category_not_found(self, client: AsyncClient, db_session: AsyncSession):
        product = await _create_product(db_session)
        await db_session.commit()

        resp = await client.post(
            f"{PRODUCTS_BASE}/{product.id}/categories",
            json={"category_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 404

    async def test_remove_category_from_product(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        product = await _create_product(db_session)
        cat = Category(name="Cacahuetes")
        db_session.add(cat)
        await db_session.flush()
        await db_session.refresh(product, ["categories"])
        product.categories.append(cat)
        await db_session.flush()
        await db_session.commit()

        resp = await client.delete(f"{PRODUCTS_BASE}/{product.id}/categories/{cat.id}")

        assert resp.status_code == 204

    async def test_remove_category_not_assigned(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        product = await _create_product(db_session)
        cat = Category(name="Cacahuetes")
        db_session.add(cat)
        await db_session.flush()
        await db_session.commit()

        resp = await client.delete(f"{PRODUCTS_BASE}/{product.id}/categories/{cat.id}")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Reset failed enrichments tests
# ---------------------------------------------------------------------------


class TestResetFailedEnrichments:
    async def test_resets_synced_without_match(self, db_session: AsyncSession):
        p = await _create_product(db_session)
        p.off_synced_at = datetime.datetime.now(datetime.UTC)
        await db_session.flush()

        count = await reset_failed_enrichments(db_session)

        assert count == 1
        await db_session.refresh(p)
        assert p.off_synced_at is None

    async def test_leaves_matched_products_alone(self, db_session: AsyncSession):
        p = await _create_product(db_session)
        p.off_synced_at = datetime.datetime.now(datetime.UTC)
        p.off_name = "Cacahuete tostado"
        p.off_code = "8480000340313"
        await db_session.flush()

        count = await reset_failed_enrichments(db_session)

        assert count == 0
        await db_session.refresh(p)
        assert p.off_synced_at is not None


class TestResetEndpoint:
    async def test_resets_failed_enrichments(self, client: AsyncClient, db_session: AsyncSession):
        product = await _create_product(db_session)
        product.off_synced_at = datetime.datetime.now(datetime.UTC)
        product.off_name = None
        await db_session.flush()
        await db_session.commit()

        resp = await client.post(f"{PRODUCTS_BASE}/enrich/reset")

        assert resp.status_code == 200
        assert resp.json()["reset"] == 1
        await db_session.refresh(product)
        assert product.off_synced_at is None

    async def test_does_not_reset_successful_enrichments(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        product = await _create_product(db_session)
        product.off_synced_at = datetime.datetime.now(datetime.UTC)
        product.off_name = "Cacahuete tostado"
        product.off_code = "123"
        await db_session.flush()
        await db_session.commit()

        resp = await client.post(f"{PRODUCTS_BASE}/enrich/reset")

        assert resp.status_code == 200
        assert resp.json()["reset"] == 0
        await db_session.refresh(product)
        assert product.off_synced_at is not None

    async def test_reset_returns_zero_when_nothing_to_reset(self, client: AsyncClient):
        resp = await client.post(f"{PRODUCTS_BASE}/enrich/reset")
        assert resp.status_code == 200
        assert resp.json()["reset"] == 0
