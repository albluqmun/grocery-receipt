import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.supermarket import Supermarket
from app.models.ticket import Ticket
from app.schemas.google_drive import DriveFile
from tests.conftest import make_extracted_receipt, unique_pdf

BASE = "/api/v1/tickets/drive"

# Patch targets — service layer, where the imports live
_SVC = "app.services.google_drive"


@pytest.fixture(autouse=True)
def _fake_settings(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "fake-key")
    monkeypatch.setattr(settings, "google_drive_credentials_path", "/fake/credentials.json")
    monkeypatch.setattr(settings, "google_drive_folder_id", "fake-folder-id")


@patch(f"{_SVC}.extract_receipt_from_pdf", new_callable=AsyncMock)
@patch(f"{_SVC}.download_file", new_callable=AsyncMock)
@patch(f"{_SVC}.list_pdf_files", new_callable=AsyncMock)
async def test_sync_success_two_files(
    mock_list: AsyncMock,
    mock_download: AsyncMock,
    mock_extract: AsyncMock,
    client: AsyncClient,
):
    pdf1, pdf2 = unique_pdf(), unique_pdf()
    mock_list.return_value = [
        DriveFile(id="drive-2", name="ticket2.pdf"),
        DriveFile(id="drive-1", name="ticket1.pdf"),
    ]
    mock_download.side_effect = [pdf1, pdf2]
    mock_extract.return_value = make_extracted_receipt()

    resp = await client.post(f"{BASE}/sync")

    assert resp.status_code == 200
    body = resp.json()
    assert body["files_found"] == 2
    assert body["files_processed"] == 2
    assert body["files_duplicate"] == 0
    assert body["files_error"] == 0
    assert body["files_skipped"] == 0
    assert len(body["results"]) == 2
    assert all(r["status"] == "processed" for r in body["results"])


@patch(f"{_SVC}.extract_receipt_from_pdf", new_callable=AsyncMock)
@patch(f"{_SVC}.download_file", new_callable=AsyncMock)
@patch(f"{_SVC}.list_pdf_files", new_callable=AsyncMock)
async def test_sync_skips_known_files(
    mock_list: AsyncMock,
    mock_download: AsyncMock,
    mock_extract: AsyncMock,
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Known drive_file_ids are filtered out; unknown files (even older) are processed."""
    supermarket = Supermarket(name="TEST SUPER", locality=None)
    db_session.add(supermarket)
    await db_session.flush()

    existing_ticket = Ticket(
        date=datetime.date(2026, 3, 20),
        supermarket_id=supermarket.id,
        total=Decimal("10.00"),
        drive_file_id="drive-old",
    )
    db_session.add(existing_ticket)
    await db_session.flush()

    mock_list.return_value = [
        DriveFile(id="drive-new", name="new_ticket.pdf"),
        DriveFile(id="drive-old", name="old_ticket.pdf"),
        DriveFile(id="drive-oldest", name="oldest_ticket.pdf"),
    ]
    mock_download.side_effect = [unique_pdf(), unique_pdf()]
    mock_extract.return_value = make_extracted_receipt()

    resp = await client.post(f"{BASE}/sync")

    assert resp.status_code == 200
    body = resp.json()
    assert body["files_found"] == 3
    # Both drive-oldest and drive-new are processed (drive-old is known)
    assert body["files_processed"] == 2
    assert len(body["results"]) == 2
    processed_names = {r["file_name"] for r in body["results"]}
    assert processed_names == {"oldest_ticket.pdf", "new_ticket.pdf"}
    assert mock_download.call_count == 2


@patch(f"{_SVC}.extract_receipt_from_pdf", new_callable=AsyncMock)
@patch(f"{_SVC}.download_file", new_callable=AsyncMock)
@patch(f"{_SVC}.list_pdf_files", new_callable=AsyncMock)
async def test_sync_empty_folder(
    mock_list: AsyncMock,
    mock_download: AsyncMock,
    mock_extract: AsyncMock,
    client: AsyncClient,
):
    mock_list.return_value = []

    resp = await client.post(f"{BASE}/sync")

    assert resp.status_code == 200
    body = resp.json()
    assert body["files_found"] == 0
    assert body["files_processed"] == 0
    assert body["files_duplicate"] == 0
    assert body["files_error"] == 0
    assert body["files_skipped"] == 0
    assert body["results"] == []
    mock_download.assert_not_called()
    mock_extract.assert_not_called()


@patch(f"{_SVC}.extract_receipt_from_pdf", new_callable=AsyncMock)
@patch(f"{_SVC}.download_file", new_callable=AsyncMock)
@patch(f"{_SVC}.list_pdf_files", new_callable=AsyncMock)
async def test_sync_invalid_pdf(
    mock_list: AsyncMock,
    mock_download: AsyncMock,
    mock_extract: AsyncMock,
    client: AsyncClient,
):
    mock_list.return_value = [DriveFile(id="drive-bad", name="not_a_pdf.pdf")]
    mock_download.return_value = b"this is not a pdf"

    resp = await client.post(f"{BASE}/sync")

    assert resp.status_code == 200
    body = resp.json()
    assert body["files_error"] == 1
    assert body["results"][0]["status"] == "error"
    assert body["results"][0]["error_code"] == "invalid_pdf"
    assert "PDF válido" in body["results"][0]["error_detail"]
    mock_extract.assert_not_called()


@patch(f"{_SVC}.extract_receipt_from_pdf", new_callable=AsyncMock)
@patch(f"{_SVC}.download_file", new_callable=AsyncMock)
@patch(f"{_SVC}.list_pdf_files", new_callable=AsyncMock)
async def test_sync_gemini_error_partial(
    mock_list: AsyncMock,
    mock_download: AsyncMock,
    mock_extract: AsyncMock,
    client: AsyncClient,
):
    """One file fails Gemini extraction, the other succeeds."""
    pdf1, pdf2 = unique_pdf(), unique_pdf()
    mock_list.return_value = [
        DriveFile(id="drive-2", name="ticket2.pdf"),
        DriveFile(id="drive-1", name="ticket1.pdf"),
    ]
    mock_download.side_effect = [pdf2, pdf1]
    mock_extract.side_effect = [make_extracted_receipt(), ValueError("unexpected")]

    resp = await client.post(f"{BASE}/sync")

    assert resp.status_code == 200
    body = resp.json()
    assert body["files_processed"] == 1
    assert body["files_error"] == 1
    error_result = next(r for r in body["results"] if r["status"] == "error")
    assert error_result["error_code"] == "internal_error"


@patch(f"{_SVC}.extract_receipt_from_pdf", new_callable=AsyncMock)
@patch(f"{_SVC}.download_file", new_callable=AsyncMock)
@patch(f"{_SVC}.list_pdf_files", new_callable=AsyncMock)
async def test_sync_rate_limit_error(
    mock_list: AsyncMock,
    mock_download: AsyncMock,
    mock_extract: AsyncMock,
    client: AsyncClient,
):
    """Gemini 429 rate limit is reported as rate_limit error code."""
    from google.genai.errors import APIError as GeminiAPIError

    mock_list.return_value = [DriveFile(id="drive-1", name="ticket1.pdf")]
    mock_download.return_value = unique_pdf()
    mock_extract.side_effect = GeminiAPIError(
        429, {"message": "Resource exhausted", "status": "RESOURCE_EXHAUSTED"}
    )

    resp = await client.post(f"{BASE}/sync")

    assert resp.status_code == 200
    body = resp.json()
    assert body["files_error"] == 1
    assert body["results"][0]["error_code"] == "rate_limit"
    assert "Resource exhausted" in body["results"][0]["error_detail"]


@patch(f"{_SVC}.extract_receipt_from_pdf", new_callable=AsyncMock)
@patch(f"{_SVC}.download_file", new_callable=AsyncMock)
@patch(f"{_SVC}.list_pdf_files", new_callable=AsyncMock)
async def test_sync_parse_error(
    mock_list: AsyncMock,
    mock_download: AsyncMock,
    mock_extract: AsyncMock,
    client: AsyncClient,
):
    """ReceiptParseError is reported as parse_error error code."""
    from app.services.gemini import ReceiptParseError

    mock_list.return_value = [DriveFile(id="drive-1", name="ticket1.pdf")]
    mock_download.return_value = unique_pdf()
    mock_extract.side_effect = ReceiptParseError("invalid decimal: '22,74'")

    resp = await client.post(f"{BASE}/sync")

    assert resp.status_code == 200
    body = resp.json()
    assert body["files_error"] == 1
    assert body["results"][0]["error_code"] == "parse_error"


@patch(f"{_SVC}.extract_receipt_from_pdf", new_callable=AsyncMock)
@patch(f"{_SVC}.download_file", new_callable=AsyncMock)
@patch(f"{_SVC}.list_pdf_files", new_callable=AsyncMock)
async def test_sync_hash_dedup(
    mock_list: AsyncMock,
    mock_download: AsyncMock,
    mock_extract: AsyncMock,
    client: AsyncClient,
):
    """A PDF with the same hash as an existing ticket is marked as duplicate."""
    same_pdf = unique_pdf()

    mock_list.return_value = [DriveFile(id="drive-1", name="ticket1.pdf")]
    mock_download.return_value = same_pdf
    mock_extract.return_value = make_extracted_receipt()
    resp1 = await client.post(f"{BASE}/sync")
    assert resp1.json()["files_processed"] == 1

    mock_list.return_value = [
        DriveFile(id="drive-2", name="ticket1_copy.pdf"),
        DriveFile(id="drive-1", name="ticket1.pdf"),
    ]
    mock_download.return_value = same_pdf

    resp2 = await client.post(f"{BASE}/sync")

    assert resp2.status_code == 200
    body = resp2.json()
    assert body["files_duplicate"] == 1
    assert body["results"][0]["status"] == "duplicate"


async def test_sync_missing_drive_config(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "google_drive_credentials_path", "")
    monkeypatch.setattr(settings, "google_drive_folder_id", "")

    resp = await client.post(f"{BASE}/sync")

    assert resp.status_code == 503
    assert "Google Drive" in resp.json()["detail"]


async def test_sync_missing_gemini_key(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")

    resp = await client.post(f"{BASE}/sync")

    assert resp.status_code == 503
    assert "GEMINI_API_KEY" in resp.json()["detail"]


@patch(f"{_SVC}.extract_receipt_from_pdf", new_callable=AsyncMock)
@patch(f"{_SVC}.download_file", new_callable=AsyncMock)
@patch(f"{_SVC}.list_pdf_files", new_callable=AsyncMock)
async def test_sync_batch_limit(
    mock_list: AsyncMock,
    mock_download: AsyncMock,
    mock_extract: AsyncMock,
    client: AsyncClient,
    monkeypatch,
):
    """When gemini_batch_limit is set, only that many files are processed."""
    monkeypatch.setattr(settings, "gemini_batch_limit", 1)

    mock_list.return_value = [
        DriveFile(id="drive-3", name="ticket3.pdf"),
        DriveFile(id="drive-2", name="ticket2.pdf"),
        DriveFile(id="drive-1", name="ticket1.pdf"),
    ]
    mock_download.return_value = unique_pdf()
    mock_extract.return_value = make_extracted_receipt()

    resp = await client.post(f"{BASE}/sync")

    assert resp.status_code == 200
    body = resp.json()
    assert body["files_found"] == 3
    assert body["files_processed"] == 1
    assert body["files_skipped"] == 2
    assert len(body["results"]) == 1
    # Oldest first after reverse, so ticket1 is processed
    assert body["results"][0]["file_name"] == "ticket1.pdf"
    assert mock_download.call_count == 1
