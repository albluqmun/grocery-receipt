import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from google.genai.errors import APIError as GeminiAPIError
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.product import Product
from app.models.supermarket import Supermarket
from app.models.ticket import Ticket
from app.schemas.receipt import ExtractedLineItem, ExtractedReceipt

BASE = "/api/v1/tickets"


def _mock_extracted(invoice_number: str | None = None) -> ExtractedReceipt:
    return ExtractedReceipt(
        supermarket_name="MERCADONA",
        supermarket_locality="TOMARES",
        invoice_number=invoice_number,
        date=datetime.date(2026, 3, 21),
        total=Decimal("62.00"),
        line_items=[
            ExtractedLineItem(
                product_name="CEBO LONCHAS",
                quantity=Decimal("1"),
                unit_price=Decimal("10.37"),
                line_total=Decimal("10.37"),
            ),
            ExtractedLineItem(
                product_name="PLATANO",
                quantity=Decimal("0.820"),
                unit_price=Decimal("2.30"),
                line_total=Decimal("1.89"),
            ),
        ],
    )


FAKE_PDF = b"%PDF-1.4 fake content"

_pdf_counter = 0


@pytest.fixture(autouse=True)
def _fake_api_key():
    original = settings.gemini_api_key
    settings.gemini_api_key = "fake-key-for-tests"
    yield
    settings.gemini_api_key = original


def _unique_pdf():
    """Generate a unique PDF payload to avoid hash-based dedup between tests."""
    global _pdf_counter
    _pdf_counter += 1
    return b"%PDF-1.4 fake content " + str(_pdf_counter).encode()


def _pdf_upload(content: bytes | None = None, content_type: str = "application/pdf"):
    return {"file": ("ticket.pdf", content or _unique_pdf(), content_type)}


@patch("app.api.tickets.extract_receipt_from_pdf", new_callable=AsyncMock)
async def test_upload_success(mock_extract: AsyncMock, client: AsyncClient):
    mock_extract.return_value = _mock_extracted()
    resp = await client.post(f"{BASE}/upload", files=_pdf_upload())

    assert resp.status_code == 200
    body = resp.json()
    assert body["supermarket"] == "MERCADONA"
    assert body["date"] == "2026-03-21"
    assert body["total"] == "62.00"
    assert body["products_created"] == 2
    assert body["products_matched"] == 0
    assert body["line_items_count"] == 2
    assert body["ticket_id"] is not None
    assert body["duplicate"] is False


@patch("app.api.tickets.extract_receipt_from_pdf", new_callable=AsyncMock)
async def test_upload_creates_entities_in_db(
    mock_extract: AsyncMock, client: AsyncClient, db_session: AsyncSession
):
    mock_extract.return_value = _mock_extracted()
    resp = await client.post(f"{BASE}/upload", files=_pdf_upload())
    assert resp.status_code == 200

    supermarkets = (await db_session.execute(select(Supermarket))).scalars().all()
    assert len(supermarkets) == 1
    assert supermarkets[0].name == "MERCADONA"
    assert supermarkets[0].locality == "TOMARES"

    products = (await db_session.execute(select(Product))).scalars().all()
    assert len(products) == 2

    tickets = (await db_session.execute(select(Ticket))).scalars().all()
    assert len(tickets) == 1
    assert tickets[0].total == Decimal("62.00")


async def test_upload_rejects_non_pdf_content_type(client: AsyncClient):
    resp = await client.post(
        f"{BASE}/upload", files={"file": ("ticket.txt", b"not a pdf", "text/plain")}
    )
    assert resp.status_code == 422
    assert "PDF" in resp.json()["detail"]


async def test_upload_rejects_spoofed_pdf(client: AsyncClient):
    resp = await client.post(
        f"{BASE}/upload",
        files={"file": ("ticket.pdf", b"not really a pdf", "application/pdf")},
    )
    assert resp.status_code == 422
    assert "PDF válido" in resp.json()["detail"]


@patch("app.api.tickets.extract_receipt_from_pdf", new_callable=AsyncMock)
async def test_upload_gemini_api_error(mock_extract: AsyncMock, client: AsyncClient):
    mock_extract.side_effect = GeminiAPIError(code=500, response_json={})
    resp = await client.post(f"{BASE}/upload", files=_pdf_upload())
    assert resp.status_code == 502


@patch("app.api.tickets.extract_receipt_from_pdf", new_callable=AsyncMock)
async def test_upload_gemini_parse_error(mock_extract: AsyncMock, client: AsyncClient):
    mock_extract.side_effect = ValueError("Invalid JSON")
    resp = await client.post(f"{BASE}/upload", files=_pdf_upload())
    assert resp.status_code == 422
    assert "extraer datos" in resp.json()["detail"]


async def test_upload_missing_api_key(client: AsyncClient):
    settings.gemini_api_key = ""
    resp = await client.post(f"{BASE}/upload", files=_pdf_upload())
    assert resp.status_code == 503
    assert "GEMINI_API_KEY" in resp.json()["detail"]


@patch("app.api.tickets.extract_receipt_from_pdf", new_callable=AsyncMock)
async def test_upload_reuses_existing_supermarket(
    mock_extract: AsyncMock, client: AsyncClient, db_session: AsyncSession
):
    mock_extract.return_value = _mock_extracted()

    await client.post(f"{BASE}/upload", files=_pdf_upload())
    mock_extract.return_value = _mock_extracted()
    await client.post(f"{BASE}/upload", files=_pdf_upload())

    supermarkets = (await db_session.execute(select(Supermarket))).scalars().all()
    assert len(supermarkets) == 1

    tickets = (await db_session.execute(select(Ticket))).scalars().all()
    assert len(tickets) == 2


@patch("app.api.tickets.extract_receipt_from_pdf", new_callable=AsyncMock)
async def test_upload_reuses_existing_products(mock_extract: AsyncMock, client: AsyncClient):
    mock_extract.return_value = _mock_extracted()
    await client.post(f"{BASE}/upload", files=_pdf_upload())

    mock_extract.return_value = _mock_extracted()
    resp = await client.post(f"{BASE}/upload", files=_pdf_upload())

    assert resp.status_code == 200
    body = resp.json()
    assert body["products_created"] == 0
    assert body["products_matched"] == 2


@patch("app.api.tickets.extract_receipt_from_pdf", new_callable=AsyncMock)
async def test_duplicate_same_pdf_skips_gemini(mock_extract: AsyncMock, client: AsyncClient):
    """Same PDF uploaded twice — second time should skip Gemini and return duplicate."""
    mock_extract.return_value = _mock_extracted()
    same_pdf = _unique_pdf()

    resp1 = await client.post(f"{BASE}/upload", files=_pdf_upload(content=same_pdf))
    assert resp1.status_code == 200
    assert resp1.json()["duplicate"] is False

    resp2 = await client.post(f"{BASE}/upload", files=_pdf_upload(content=same_pdf))
    assert resp2.status_code == 200
    assert resp2.json()["duplicate"] is True
    assert resp2.json()["ticket_id"] == resp1.json()["ticket_id"]

    # Gemini should only be called once (second upload was skipped by hash)
    assert mock_extract.call_count == 1


@patch("app.api.tickets.extract_receipt_from_pdf", new_callable=AsyncMock)
async def test_duplicate_same_invoice_different_pdf(mock_extract: AsyncMock, client: AsyncClient):
    """Different PDF but same invoice number — should detect duplicate via invoice."""
    mock_extract.return_value = _mock_extracted(invoice_number="3823-014-675403")

    resp1 = await client.post(f"{BASE}/upload", files=_pdf_upload())
    assert resp1.status_code == 200
    assert resp1.json()["duplicate"] is False

    mock_extract.return_value = _mock_extracted(invoice_number="3823-014-675403")
    resp2 = await client.post(f"{BASE}/upload", files=_pdf_upload())
    assert resp2.status_code == 200
    assert resp2.json()["duplicate"] is True
    assert resp2.json()["ticket_id"] == resp1.json()["ticket_id"]
