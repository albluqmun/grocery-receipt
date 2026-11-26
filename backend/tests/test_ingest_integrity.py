"""Ingest integrity: partial tickets, schema bounds, insert races, Drive re-processing."""

import datetime
import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models.line_item import LineItem
from app.models.processed_drive_file import ProcessedDriveFile
from app.models.supermarket import Supermarket
from app.models.ticket import Ticket
from app.schemas.google_drive import DriveFile
from app.schemas.receipt import ExtractedLineItem, ExtractedReceipt
from app.services import receipt as receipt_service
from app.services.gemini import ReceiptParseError, extract_receipt_from_pdf, match_products_with_off
from tests.conftest import make_extracted_receipt, unique_pdf

_DRIVE = "app.services.google_drive"
_UPLOAD = "app.api.tickets.extract_receipt_from_pdf"


@pytest.fixture(autouse=True)
def _fake_settings(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "fake-key")
    monkeypatch.setattr(settings, "google_drive_credentials_path", "/fake/credentials.json")
    monkeypatch.setattr(settings, "google_drive_folder_id", "fake-folder-id")


@pytest.fixture(autouse=True)
def _no_enrichment():
    with patch("app.services.receipt.enrich_products", new_callable=AsyncMock) as m:
        yield m


async def _count(db: AsyncSession, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


def _item(name="LECHE", qty="1", unit="1.00", total="1.00") -> ExtractedLineItem:
    return ExtractedLineItem(
        product_name=name,
        quantity=Decimal(qty),
        unit_price=Decimal(unit),
        line_total=Decimal(total),
    )


def _receipt(items: list[ExtractedLineItem], invoice: str | None = None) -> ExtractedReceipt:
    return ExtractedReceipt(
        supermarket_name="MERCADONA",
        invoice_number=invoice,
        date=datetime.date(2026, 3, 21),
        total=Decimal("10.00"),
        line_items=items,
    )


# --- C5: no partial tickets ---------------------------------------------------


async def test_discount_lines_are_filtered(db_session: AsyncSession):
    receipt = _receipt([_item("LECHE"), _item("DESCUENTO", "1", "-0.50", "-0.50"), _item("X", "0")])

    resp = await receipt_service.process_extracted_receipt(db_session, receipt, "h" * 64)

    assert resp.line_items_count == 1
    assert await _count(db_session, LineItem) == 1


async def test_receipt_without_valid_lines_is_rejected_without_ticket(db_session: AsyncSession):
    receipt = _receipt([_item("DESCUENTO", "1", "-0.50", "-0.50")])

    with pytest.raises(ReceiptParseError):
        await receipt_service.process_extracted_receipt(db_session, receipt, "h" * 64)

    assert await _count(db_session, Ticket) == 0
    assert await _count(db_session, Supermarket) == 0


async def test_upload_without_valid_lines_returns_422(client: AsyncClient):
    with patch(_UPLOAD, new_callable=AsyncMock) as mock_extract:
        mock_extract.return_value = _receipt([_item("DESCUENTO", "1", "-1.00", "-1.00")])
        resp = await client.post(
            "/api/v1/tickets/upload",
            files={"file": ("t.pdf", unique_pdf(), "application/pdf")},
        )
    assert resp.status_code == 422


async def test_failure_mid_ticket_leaves_nothing_behind(db_session: AsyncSession):
    """A failure after the ticket flush leaves no ticket/lines and keeps the session usable."""
    from app.services import line_item as line_item_service

    original = line_item_service.create
    calls = 0

    async def flaky(db, ticket_id, data):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("boom")
        return await original(db, ticket_id, data)

    receipt = _receipt([_item("A"), _item("B")])
    with patch.object(line_item_service, "create", flaky):
        with pytest.raises(RuntimeError):
            await receipt_service.process_extracted_receipt(db_session, receipt, "h" * 64)

    assert await _count(db_session, Ticket) == 0
    assert await _count(db_session, LineItem) == 0
    # session still usable
    resp = await receipt_service.process_extracted_receipt(db_session, receipt, "i" * 64)
    assert resp.line_items_count == 2


@patch(f"{_DRIVE}.extract_receipt_from_pdf", new_callable=AsyncMock)
@patch(f"{_DRIVE}.download_file", new_callable=AsyncMock)
@patch(f"{_DRIVE}.list_pdf_files", new_callable=AsyncMock)
async def test_sync_batch_survives_failing_file(
    mock_list: AsyncMock,
    mock_download: AsyncMock,
    mock_extract: AsyncMock,
    client: AsyncClient,
    db_session: AsyncSession,
):
    """First file fails midway; no partial ticket and the second file still persists."""
    from app.services import line_item as line_item_service

    mock_list.return_value = [
        DriveFile(id="d-2", name="ok.pdf"),
        DriveFile(id="d-1", name="bad.pdf"),
    ]
    mock_download.side_effect = [unique_pdf(), unique_pdf()]
    mock_extract.side_effect = [_receipt([_item("A"), _item("B")]), _receipt([_item("C")])]

    original = line_item_service.create
    calls = 0

    async def flaky(db, ticket_id, data):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("boom")
        return await original(db, ticket_id, data)

    with patch.object(line_item_service, "create", flaky):
        resp = await client.post("/api/v1/tickets/drive/sync")

    body = resp.json()
    assert resp.status_code == 200
    assert body["files_error"] == 1
    assert body["files_processed"] == 1
    assert await _count(db_session, Ticket) == 1
    assert await _count(db_session, LineItem) == 1


# --- R10: bounds on extracted data --------------------------------------------


def test_extracted_schema_rejects_out_of_range():
    with pytest.raises(ValidationError):
        _item(name="x" * 301)
    with pytest.raises(ValidationError):
        _item(total="123456789.00")
    with pytest.raises(ValidationError):
        _item(qty="12345678")
    with pytest.raises(ValidationError):
        ExtractedReceipt(
            supermarket_name="x" * 201,
            date=datetime.date(2026, 1, 1),
            total=Decimal("1"),
            line_items=[],
        )
    with pytest.raises(ValidationError):
        ExtractedReceipt(
            supermarket_name="M", date=datetime.date(2026, 1, 1), total=Decimal("0"), line_items=[]
        )


def test_extracted_schema_rounds_extra_decimals():
    item = _item(unit="1.4567", total="2.999")
    assert item.unit_price == Decimal("1.46")
    assert item.line_total == Decimal("3.00")


async def test_gemini_out_of_range_data_raises_parse_error():
    payload = {
        "supermarket_name": "MERCADONA",
        "date": "2026-03-21",
        "total": 99999999999.5,
        "line_items": [],
    }
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=MagicMock(text=json.dumps(payload)))
    with patch("app.services.gemini._get_client", return_value=client):
        with pytest.raises(ReceiptParseError):
            await extract_receipt_from_pdf(b"%PDF-1.4")


# --- C9/R11: find-or-create races ---------------------------------------------


async def test_pdf_hash_race_returns_duplicate(db_session: AsyncSession):
    first = await receipt_service.process_extracted_receipt(
        db_session, _receipt([_item()]), "a" * 64
    )
    # Same hash reaches the insert (the pre-check was lost to a concurrent request)
    second = await receipt_service.process_extracted_receipt(
        db_session, _receipt([_item()]), "a" * 64
    )
    assert second.duplicate is True
    assert second.ticket_id == first.ticket_id
    assert await _count(db_session, Ticket) == 1


async def test_invoice_number_race_returns_duplicate(db_session: AsyncSession):
    first = await receipt_service.process_extracted_receipt(
        db_session, _receipt([_item()], invoice="INV-1"), "a" * 64
    )
    real = receipt_service._find_by_invoice_number
    lookup = AsyncMock(side_effect=[None, await real(db_session, "INV-1")])
    with patch.object(receipt_service, "_find_by_invoice_number", lookup):
        second = await receipt_service.process_extracted_receipt(
            db_session, _receipt([_item()], invoice="INV-1"), "b" * 64
        )
    assert second.duplicate is True
    assert second.ticket_id == first.ticket_id
    assert await _count(db_session, Ticket) == 1


async def test_supermarket_race_reuses_existing(db_session: AsyncSession, engine):
    from app.services import supermarket as supermarket_service

    original = supermarket_service.create

    async def racing_create(db, data):
        # A concurrent request commits the same name first
        async with async_sessionmaker(engine, expire_on_commit=False)() as other:
            other.add(Supermarket(name=data.name))
            await other.commit()
        return await original(db, data)

    with patch.object(supermarket_service, "create", racing_create):
        resp = await receipt_service.process_extracted_receipt(
            db_session, _receipt([_item()]), "a" * 64
        )

    assert resp.duplicate is False
    assert await _count(db_session, Supermarket) == 1
    assert await _count(db_session, Ticket) == 1


async def test_unrelated_integrity_error_is_not_swallowed(db_session: AsyncSession):
    with patch.object(
        receipt_service.ticket_service,
        "create",
        AsyncMock(side_effect=IntegrityError("stmt", {}, Exception("x"))),
    ):
        with pytest.raises(IntegrityError):
            await receipt_service.process_extracted_receipt(
                db_session, _receipt([_item()]), "z" * 64
            )


# --- C8: Drive duplicates / invalid PDFs are not re-processed ------------------


@patch(f"{_DRIVE}.extract_receipt_from_pdf", new_callable=AsyncMock)
@patch(f"{_DRIVE}.download_file", new_callable=AsyncMock)
@patch(f"{_DRIVE}.list_pdf_files", new_callable=AsyncMock)
async def test_sync_does_not_redownload_invalid_pdf(
    mock_list: AsyncMock,
    mock_download: AsyncMock,
    mock_extract: AsyncMock,
    client: AsyncClient,
    db_session: AsyncSession,
):
    mock_list.return_value = [DriveFile(id="d-bad", name="bad.pdf")]
    mock_download.return_value = b"not a pdf"

    first = await client.post("/api/v1/tickets/drive/sync")
    assert first.json()["files_error"] == 1
    assert mock_download.call_count == 1

    second = await client.post("/api/v1/tickets/drive/sync")
    assert second.json()["results"] == []
    assert mock_download.call_count == 1
    assert await _count(db_session, ProcessedDriveFile) == 1


@patch(f"{_DRIVE}.extract_receipt_from_pdf", new_callable=AsyncMock)
@patch(f"{_DRIVE}.download_file", new_callable=AsyncMock)
@patch(f"{_DRIVE}.list_pdf_files", new_callable=AsyncMock)
async def test_sync_does_not_redownload_duplicates(
    mock_list: AsyncMock,
    mock_download: AsyncMock,
    mock_extract: AsyncMock,
    client: AsyncClient,
):
    same = unique_pdf()
    mock_list.return_value = [
        DriveFile(id="d-2", name="copy.pdf"),
        DriveFile(id="d-1", name="o.pdf"),
    ]
    mock_download.side_effect = [same, same]
    mock_extract.return_value = make_extracted_receipt()

    first = await client.post("/api/v1/tickets/drive/sync")
    assert first.json()["files_processed"] == 1
    assert first.json()["files_duplicate"] == 1
    assert mock_download.call_count == 2

    second = await client.post("/api/v1/tickets/drive/sync")
    assert second.json()["results"] == []
    assert mock_download.call_count == 2
    assert mock_extract.call_count == 1


@patch(f"{_DRIVE}.extract_receipt_from_pdf", new_callable=AsyncMock)
@patch(f"{_DRIVE}.download_file", new_callable=AsyncMock)
@patch(f"{_DRIVE}.list_pdf_files", new_callable=AsyncMock)
async def test_sync_retries_transient_errors(
    mock_list: AsyncMock,
    mock_download: AsyncMock,
    mock_extract: AsyncMock,
    client: AsyncClient,
):
    """Parse/Gemini errors may be transient: they are NOT registered as processed."""
    mock_list.return_value = [DriveFile(id="d-1", name="t.pdf")]
    mock_download.return_value = unique_pdf()
    mock_extract.side_effect = ReceiptParseError("bad")

    await client.post("/api/v1/tickets/drive/sync")
    await client.post("/api/v1/tickets/drive/sync")

    assert mock_download.call_count == 2


# --- C11: match_products_with_off ----------------------------------------------


async def test_match_returns_empty_when_client_init_fails():
    """Previously raised UnboundLocalError when the failure happened before `response`."""
    from app.schemas.enrichment import OFFCandidate

    cands = {"X": [OFFCandidate(code="1", product_name="x")]}
    with patch("app.services.gemini._get_client", side_effect=ValueError("no key")):
        assert await match_products_with_off(cands) == {}


@pytest.mark.parametrize("text", ["[]", '"str"', "null", "42"])
async def test_match_returns_empty_when_json_is_not_object(text: str):
    from app.schemas.enrichment import OFFCandidate

    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=MagicMock(text=text))
    cands = {"X": [OFFCandidate(code="1", product_name="x")]}
    with patch("app.services.gemini._get_client", return_value=client):
        assert await match_products_with_off(cands) == {}
