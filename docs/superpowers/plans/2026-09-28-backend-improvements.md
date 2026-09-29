# Backend Improvements (P1.1, P1.2, P1.5, P2, P3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the three highest-confidence P1 correctness/robustness findings, all P2 consistency findings except the "incomplete CRUD" one (confirmed intentional), and all P3 polish findings from the 8-agent backend code review, on branch `fixes/improvements-backend-202609`.

**Architecture:** No new services or layers beyond what CLAUDE.md already documents (api/services/models/schemas/core). Two small additions: a `google_drive_client.py` adapter (splits Drive API plumbing out of orchestration) and a `services/common.py` helper (`get_or_create_many`, used by both product and category batch-resolution, removing duplicated find-or-create logic).

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (async), PostgreSQL, Alembic, pytest — unchanged. No new dependencies, no new migrations (no schema changes — only relationship *loading strategy* and Python-level typing change).

**Spec:** This plan's own "Scope" section below is the spec — it was derived directly from `architecture-strategist`'s subagent report (P1-1..P1-5, P2-1..P2-10, P3) during the full-backend review earlier in this conversation, filtered to the user's explicit selection: P1-1, P1-2, P1-5, all of P2 except P2-7 (intentionally-incomplete CRUD, confirmed by the user as fine as-is), and all of P3. P1-3 (merge PDF ingestion pipeline), P1-4 (Gemini SDK exception leakage), and P2-7 are explicitly OUT of scope for this branch.

## Global Constraints

- Python 3.12+, async everywhere, ruff line-length=100 (`docker compose exec api ruff check app/` / `ruff format app/` must stay clean after every task).
- Service functions stay free async functions (no classes), use `db.flush()` never `db.commit()`.
- Spanish only in `HTTPException.detail` strings; everything else (code, logs, docstrings) in English.
- Every task must leave `docker compose exec api pytest` green before moving to the next task.
- No new Alembic migration in this plan — every change here is either a relationship-loading-strategy change (Python-only) or a pure code move/refactor with no schema impact.
- Do not touch: PDF ingestion pipeline duplication (router vs. drive_sync), Gemini SDK exception leakage across layers, or any of the "incomplete CRUD" surface (supermarkets POST/PATCH, line_items router, tickets PATCH, `TicketRead.lines`/`supermarket`/`invoice_number`) — all confirmed out of scope.

## Review Focus

- **Removing inline enrichment must not silently break the "duplicate ticket" response**, since `ReceiptUploadResponse.duplicate_from` still needs `ticket.supermarket.name` after `Ticket.supermarket` becomes `lazy="raise"` — covered in Task 3's explicit `selectinload` fix and exercised by the existing duplicate-detection tests.
- **The Drive-sync savepoint fix must be proven with a *real* DB-level failure**, not a mocked Python exception, or the regression test would pass identically with or without the fix — Task 1 uses a genuine bad-SQL statement to reproduce actual asyncpg transaction poisoning.
- **Switching `Ticket.lines` to `lazy="raise"` must not silently break cascade-delete of line items**, since SQLAlchemy's ORM-level `delete-orphan` cascade normally needs the collection loaded — Task 3 adds `passive_deletes=True` (matching the existing DB-level `ON DELETE CASCADE`) and a dedicated test that deletes a ticket with line items and verifies they're actually gone from the DB.
- **Consolidating `enrich_products`/`enrich_pending` must not silently drop the per-supermarket Gemini matching hint** that `enrich_pending` computes today via a 2-query-per-product loop — Task 5's replacement single-query hint lookup is tested against the existing `test_passes_supermarket_name_to_gemini` assertion (rewritten, not deleted).
- **Changing service import style (`from X import func` → `from app.services import X as x_service`) breaks `unittest.mock.patch` targets that reference the old import path** — every task that changes an import style enumerates every test file whose `@patch(...)` target must move, so none silently stop mocking (which would make tests pass for the wrong reason — hitting real external APIs).

---

## Scope (from architecture-strategist's report, numbered as the user referenced it)

**In scope:** P1-1, P1-2, P1-5, P2-1, P2-2, P2-3, P2-4, P2-5, P2-6, P2-8, P2-9, P2-10, all P3 items.
**Out of scope (explicitly excluded by the user):** P1-3, P1-4, P2-7, and every other reviewer's findings not listed above (docker-compose network exposure, `products.name` unique constraint, FK index verification, missing test coverage, return-type annotations, `raise ... from exc`, DB `CHECK` constraints, etc.) — future work if requested.

---

## Task 1: P1-1 — Savepoint isolation in Google Drive sync

**Files:**
- Modify: `backend/app/services/google_drive.py:129-186` (`sync_drive_folder`)
- Test: `backend/tests/test_drive_sync.py`

**Interfaces:**
- Consumes: `AsyncSession.begin_nested()` (SQLAlchemy 2.0 async API, no new dependency).
- Produces: no change to `sync_drive_folder`'s signature or `DriveSyncResponse` shape — later tasks that touch this file build on this version.

- [ ] **Step 1: Write the failing regression test**

Add to `backend/tests/test_drive_sync.py` (needs `from sqlalchemy import text` and `from app.services import google_drive as google_drive_service` added to the imports at the top of the file):

```python
async def test_sync_isolates_db_failure_to_one_file(
    client: AsyncClient,
    monkeypatch,
):
    """A real DB-level error while processing one file must not poison the session
    for subsequent files in the same sync batch (regression test for the P1-1 fix)."""
    monkeypatch.setattr(settings, "gemini_api_key", "fake-key")
    monkeypatch.setattr(settings, "google_drive_credentials_path", "/fake/credentials.json")
    monkeypatch.setattr(settings, "google_drive_folder_id", "fake-folder-id")

    pdf_bad, pdf_good = unique_pdf(), unique_pdf()
    original_process = google_drive_service._process_single_file

    async def patched_process(db, df):
        if df.id == "drive-bad":
            # Trigger a REAL DB-level error (a mocked Python exception would not
            # actually poison the asyncpg transaction, so it wouldn't prove anything).
            await db.execute(text("SELECT * FROM no_such_table_xyz"))
        return await original_process(db, df)

    with (
        patch(f"{_SVC}.list_pdf_files", new_callable=AsyncMock) as mock_list,
        patch(f"{_SVC}.download_file", new_callable=AsyncMock) as mock_download,
        patch(f"{_SVC}.extract_receipt_from_pdf", new_callable=AsyncMock) as mock_extract,
        patch(f"{_SVC}._process_single_file", side_effect=patched_process),
    ):
        # Newest first (as returned by Drive); sync_drive_folder reverses to oldest-first,
        # so drive-bad is processed BEFORE drive-good.
        mock_list.return_value = [
            DriveFile(id="drive-good", name="good.pdf"),
            DriveFile(id="drive-bad", name="bad.pdf"),
        ]
        mock_download.side_effect = [pdf_bad, pdf_good]
        mock_extract.return_value = make_extracted_receipt()

        resp = await client.post(f"{BASE}/sync")

    assert resp.status_code == 200
    body = resp.json()
    assert body["files_error"] == 1
    assert body["files_processed"] == 1
    processed = next(r for r in body["results"] if r["status"] == "processed")
    assert processed["file_name"] == "good.pdf"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec api pytest tests/test_drive_sync.py::test_sync_isolates_db_failure_to_one_file -v`
Expected: FAIL — without the savepoint, the second file's real `db.flush()` inside `process_extracted_receipt` raises `sqlalchemy.exc.PendingRollbackError` (session poisoned by the first file's raw failed statement), so `files_processed == 0` and `files_error == 2`.

- [ ] **Step 3: Wrap per-file processing in a savepoint**

In `backend/app/services/google_drive.py`, change the loop body of `sync_drive_folder` (currently lines ~154-182):

```python
    results: list[DriveSyncFileResult] = []
    for df in pending:
        try:
            async with db.begin_nested():
                result = await _process_single_file(db, df)
        except GeminiAPIError as exc:
            logger.exception("Gemini API error for '%s' (id=%s)", df.name, df.id)
            error_code = SyncErrorCode.RATE_LIMIT if exc.code == 429 else SyncErrorCode.GEMINI_ERROR
            result = DriveSyncFileResult(
                file_name=df.name,
                status=SyncFileStatus.ERROR,
                error_code=error_code,
                error_detail=exc.message or str(exc),
            )
        except ReceiptParseError as exc:
            logger.exception("Parse error for '%s' (id=%s)", df.name, df.id)
            result = DriveSyncFileResult(
                file_name=df.name,
                status=SyncFileStatus.ERROR,
                error_code=SyncErrorCode.PARSE_ERROR,
                error_detail=str(exc),
            )
        except Exception:
            logger.exception("Unexpected error for '%s' (id=%s)", df.name, df.id)
            result = DriveSyncFileResult(
                file_name=df.name,
                status=SyncFileStatus.ERROR,
                error_code=SyncErrorCode.INTERNAL_ERROR,
                error_detail="Error inesperado al procesar el ticket",
            )
        results.append(result)
```

(Only the `try:` line changes — it now opens `async with db.begin_nested():` and the `result = await _process_single_file(db, df)` line is indented one level further. No other line in this loop changes.)

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec api pytest tests/test_drive_sync.py -v`
Expected: all tests PASS, including the new one.

- [ ] **Step 5: Run full suite and lint**

Run: `docker compose exec api pytest && docker compose exec api ruff check app/ && docker compose exec api ruff format --check app/`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/google_drive.py backend/tests/test_drive_sync.py
git commit -m "fix(P1-1): isolate Drive sync per-file DB errors with a savepoint"
```

---

## Task 2: P1-2 — Decouple enrichment from ticket ingestion

**Files:**
- Modify: `backend/app/services/receipt.py`
- Modify: `backend/app/schemas/receipt.py`
- Test: `backend/tests/test_enrichment.py` (remove `TestTicketUploadEnrichment`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `process_extracted_receipt(...)` returns a `ReceiptUploadResponse` **without** a `products_enriched` field. New products are left with `off_synced_at IS NULL`, to be picked up later by `POST /products/enrich` (`enrich_pending`) — that queue already exists and needs no change.

- [ ] **Step 1: Remove the field from the response schema**

In `backend/app/schemas/receipt.py`, remove this line from `ReceiptUploadResponse`:

```python
    products_enriched: int = Field(default=0, examples=[5])
```

- [ ] **Step 2: Remove the inline enrichment call from the service**

In `backend/app/services/receipt.py`, remove the import:

```python
from app.services.enrichment import enrich_products
```

Replace the tail of `process_extracted_receipt` (currently from the `# Collect newly created products for enrichment` comment through the final `return`) with:

```python
    logger.info(
        "Ticket %s saved: %d new products, %d matched, %d line items",
        ticket.id,
        products_created,
        products_matched,
        len(data.line_items),
    )
    return ReceiptUploadResponse(
        ticket_id=ticket.id,
        supermarket=supermarket.name,
        date=ticket.date,
        total=ticket.total,
        products_created=products_created,
        products_matched=products_matched,
        line_items_count=len(data.line_items),
    )
```

- [ ] **Step 3: Remove the now-obsolete inline-enrichment tests**

In `backend/tests/test_enrichment.py`, delete the entire `TestTicketUploadEnrichment` class (both `test_upload_triggers_enrichment` and `test_upload_succeeds_when_enrichment_fails` — this behavior no longer exists, enrichment is now always out-of-band via `POST /products/enrich`).

- [ ] **Step 4: Run tests**

Run: `docker compose exec api pytest tests/test_enrichment.py tests/test_receipts.py tests/test_drive_sync.py -v`
Expected: all PASS. (`test_receipts.py::test_upload_success` does not assert on `products_enriched`, so it is unaffected.)

- [ ] **Step 5: Run full suite and lint**

Run: `docker compose exec api pytest && docker compose exec api ruff check app/ && docker compose exec api ruff format --check app/`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/receipt.py backend/app/schemas/receipt.py backend/tests/test_enrichment.py
git commit -m "fix(P1-2): decouple product enrichment from ticket ingestion"
```

---

## Task 3: P1-5 + P2-9 — Fix eager-loading cycles, add typed/back_populates relationships

**Files:**
- Modify: `backend/app/models/category.py`, `product.py`, `ticket.py`, `line_item.py`, `supermarket.py`
- Modify: `backend/app/services/receipt.py` (`find_by_pdf_hash`, `_find_by_invoice_number` need explicit `selectinload(Ticket.supermarket)` now that it's no longer eager by default)
- Test: `backend/tests/test_tickets.py`, `backend/tests/test_categories.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Ticket.supermarket`, `Ticket.lines`, `LineItem.ticket`, `LineItem.product`, `Category.products` all become `lazy="raise"` (no more automatic eager loading). `Product.categories` stays `lazy="selectin"` (still needed by `ProductRead`). New reverse relationships: `Supermarket.tickets`, `Product.line_items` (both `lazy="raise"`, for typing/back_populates completeness only — nothing accesses them yet).

- [ ] **Step 1: Write the failing tests first**

Add to `backend/tests/test_tickets.py` (needs `from decimal import Decimal`, `from sqlalchemy import select`, `from app.models.line_item import LineItem` added to imports):

```python
async def test_delete_cascades_line_items(client: AsyncClient, db_session: AsyncSession):
    """Deleting a ticket with line items must cascade-delete them (DB-level ON DELETE CASCADE)."""
    from app.models.product import Product
    from app.services import line_item as line_item_service
    from app.schemas.line_item import LineItemCreate

    sm = await _create_supermarket(db_session)
    ticket = await _create_ticket(db_session, sm)
    product = Product(name="Leche")
    db_session.add(product)
    await db_session.flush()
    await line_item_service.create(
        db_session,
        ticket.id,
        LineItemCreate(
            product_id=product.id,
            quantity=Decimal("1"),
            unit_price=Decimal("1.50"),
            line_total=Decimal("1.50"),
        ),
    )
    await db_session.commit()

    resp = await client.delete(f"{BASE}/{ticket.id}")

    assert resp.status_code == 204
    remaining = (
        await db_session.execute(select(LineItem).where(LineItem.ticket_id == ticket.id))
    ).scalars().all()
    assert remaining == []


async def test_get_ticket_with_line_items_does_not_error(
    client: AsyncClient, db_session: AsyncSession
):
    """GET must not attempt to eager-load lines/supermarket now that they're lazy='raise'."""
    from app.models.product import Product
    from app.services import line_item as line_item_service
    from app.schemas.line_item import LineItemCreate

    sm = await _create_supermarket(db_session)
    ticket = await _create_ticket(db_session, sm)
    product = Product(name="Leche")
    db_session.add(product)
    await db_session.flush()
    await line_item_service.create(
        db_session,
        ticket.id,
        LineItemCreate(
            product_id=product.id,
            quantity=Decimal("1"),
            unit_price=Decimal("1.50"),
            line_total=Decimal("1.50"),
        ),
    )
    await db_session.commit()

    resp = await client.get(f"{BASE}/{ticket.id}")
    assert resp.status_code == 200

    resp_list = await client.get(BASE)
    assert resp_list.status_code == 200
```

Add to `backend/tests/test_categories.py`:

```python
async def test_get_category_with_products_does_not_error(
    client: AsyncClient, db_session: AsyncSession
):
    """GET must not attempt to eager-load products now that Category.products is lazy='raise'."""
    cat = await _create_category(db_session)
    product = Product(name="Leche")
    db_session.add(product)
    await db_session.flush()
    await db_session.execute(
        product_categories.insert().values(product_id=product.id, category_id=cat.id)
    )
    await db_session.commit()

    resp = await client.get(f"{BASE}/{cat.id}")
    assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail or error appropriately**

Run: `docker compose exec api pytest tests/test_tickets.py tests/test_categories.py -v`
Expected: `test_delete_cascades_line_items` currently passes by accident (cascade already works at the DB level), but `test_get_ticket_with_line_items_does_not_error` and `test_get_category_with_products_does_not_error` also currently pass (nothing is `lazy="raise"` yet) — these are regression guards for the change about to be made, confirmed green as a baseline before the model edit.

- [ ] **Step 3: Update the models**

Replace `backend/app/models/category.py` with:

```python
from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.product import Product


class Category(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "categories"

    name: Mapped[str] = mapped_column(String(200), unique=True)
    external_id: Mapped[str | None] = mapped_column(String(100))

    products: Mapped[list["Product"]] = relationship(
        "Product", secondary="product_categories", back_populates="categories", lazy="raise"
    )
```

Replace `backend/app/models/product.py` with:

```python
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.category import Category
    from app.models.line_item import LineItem

product_categories = Table(
    "product_categories",
    Base.metadata,
    Column("product_id", ForeignKey("products.id", ondelete="CASCADE"), primary_key=True),
    Column("category_id", ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True),
)


class Product(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "products"

    name: Mapped[str] = mapped_column(String(300))
    brand: Mapped[str | None] = mapped_column(String(200))

    # Open Food Facts enrichment fields
    off_code: Mapped[str | None] = mapped_column(String(50))
    off_name: Mapped[str | None] = mapped_column(String(300))
    off_image_url: Mapped[str | None] = mapped_column(Text)
    off_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    categories: Mapped[list["Category"]] = relationship(
        "Category", secondary=product_categories, back_populates="products", lazy="selectin"
    )
    line_items: Mapped[list["LineItem"]] = relationship(
        "LineItem", back_populates="product", lazy="raise"
    )
```

Replace `backend/app/models/ticket.py` with:

```python
import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.line_item import LineItem
    from app.models.supermarket import Supermarket


class Ticket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tickets"

    date: Mapped[date]
    supermarket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("supermarkets.id"), index=True)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    invoice_number: Mapped[str | None] = mapped_column(String(100), unique=True)
    pdf_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    drive_file_id: Mapped[str | None] = mapped_column(String(100), unique=True)

    supermarket: Mapped["Supermarket"] = relationship(
        "Supermarket", back_populates="tickets", lazy="raise"
    )
    lines: Mapped[list["LineItem"]] = relationship(
        "LineItem",
        back_populates="ticket",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
```

Replace `backend/app/models/line_item.py` with:

```python
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.ticket import Ticket


class LineItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "line_items"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="lines", lazy="raise")
    product: Mapped["Product"] = relationship(
        "Product", back_populates="line_items", lazy="raise"
    )
```

Replace `backend/app/models/supermarket.py` with:

```python
from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.ticket import Ticket


class Supermarket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "supermarkets"

    name: Mapped[str] = mapped_column(String(200), unique=True)
    locality: Mapped[str | None] = mapped_column(String(200))

    tickets: Mapped[list["Ticket"]] = relationship(
        "Ticket", back_populates="supermarket", lazy="raise"
    )
```

- [ ] **Step 4: Fix `duplicate_from`'s dependency on `Ticket.supermarket`**

`ReceiptUploadResponse.duplicate_from(ticket)` reads `ticket.supermarket.name`. Now that `Ticket.supermarket` is `lazy="raise"`, the two lookup functions that feed it must eager-load it explicitly. In `backend/app/services/receipt.py`, add the import `from sqlalchemy.orm import selectinload` and change:

```python
async def find_by_pdf_hash(db: AsyncSession, pdf_hash: str) -> Ticket | None:
    result = await db.execute(select(Ticket).where(Ticket.pdf_hash == pdf_hash))
    return result.scalar_one_or_none()
```

to:

```python
async def find_by_pdf_hash(db: AsyncSession, pdf_hash: str) -> Ticket | None:
    result = await db.execute(
        select(Ticket).options(selectinload(Ticket.supermarket)).where(Ticket.pdf_hash == pdf_hash)
    )
    return result.scalar_one_or_none()
```

and:

```python
async def _find_by_invoice_number(db: AsyncSession, invoice_number: str) -> Ticket | None:
    result = await db.execute(select(Ticket).where(Ticket.invoice_number == invoice_number))
    return result.scalar_one_or_none()
```

to:

```python
async def _find_by_invoice_number(db: AsyncSession, invoice_number: str) -> Ticket | None:
    result = await db.execute(
        select(Ticket)
        .options(selectinload(Ticket.supermarket))
        .where(Ticket.invoice_number == invoice_number)
    )
    return result.scalar_one_or_none()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec api pytest tests/test_tickets.py tests/test_categories.py tests/test_receipts.py tests/test_drive_sync.py tests/test_products.py tests/test_enrichment.py -v`
Expected: all PASS. In particular `test_duplicate_same_pdf_skips_gemini` and `test_duplicate_same_invoice_different_pdf` (both rely on `duplicate_from` reading `ticket.supermarket.name`) must still pass — they exercise the fix from Step 4.

- [ ] **Step 6: Run full suite and lint**

Run: `docker compose exec api pytest && docker compose exec api ruff check app/ && docker compose exec api ruff format --check app/`

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/ backend/app/services/receipt.py backend/tests/test_tickets.py backend/tests/test_categories.py
git commit -m "fix(P1-5,P2-9): stop eager-loading relationship cycles, type relationships"
```

---

## Task 4: P2-4a — Split the Google Drive API adapter from sync orchestration

**Files:**
- Create: `backend/app/services/google_drive_client.py`
- Modify: `backend/app/services/google_drive.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `list_pdf_files`, `download_file` now live in `google_drive_client.py`, but are re-imported into `google_drive.py` so every existing `@patch("app.services.google_drive.list_pdf_files", ...)` / `@patch("app.services.google_drive.download_file", ...)` in `test_drive_sync.py` **keeps working unchanged** (patching an attribute works the same whether it was defined there or merely imported there).

- [ ] **Step 1: Create the adapter module**

Create `backend/app/services/google_drive_client.py`:

```python
import asyncio
import io

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from app.core.config import settings
from app.schemas.google_drive import DriveFile

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

_service = None


def _get_service():
    """Lazily initialize the Google Drive API service (singleton)."""
    global _service
    if _service is None:
        credentials = service_account.Credentials.from_service_account_file(
            settings.google_drive_credentials_path, scopes=SCOPES
        )
        _service = build("drive", "v3", credentials=credentials)
    return _service


def _list_pdf_files_sync(folder_id: str) -> list[DriveFile]:
    """List PDF files in a Drive folder, ordered by createdTime desc."""
    service = _get_service()
    query = f"'{folder_id}' in parents and mimeType='application/pdf' and trashed=false"
    files: list[DriveFile] = []
    page_token = None

    while True:
        response = (
            service.files()
            .list(
                q=query,
                fields="nextPageToken, files(id, name)",
                orderBy="createdTime desc",
                pageSize=100,
                pageToken=page_token,
            )
            .execute()
        )
        for f in response.get("files", []):
            files.append(DriveFile(id=f["id"], name=f["name"]))

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return files


def _download_file_sync(file_id: str) -> bytes:
    """Download a file's content from Google Drive."""
    service = _get_service()
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


async def list_pdf_files(folder_id: str) -> list[DriveFile]:
    """List PDF files in a Drive folder (async wrapper)."""
    return await asyncio.to_thread(_list_pdf_files_sync, folder_id)


async def download_file(file_id: str) -> bytes:
    """Download a file from Google Drive (async wrapper)."""
    return await asyncio.to_thread(_download_file_sync, file_id)
```

- [ ] **Step 2: Trim `google_drive.py` down to orchestration only**

Replace the top of `backend/app/services/google_drive.py` (everything above `async def _process_single_file`) with:

```python
import logging

from google.genai.errors import APIError as GeminiAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.schemas.google_drive import (
    DriveFile,
    DriveSyncFileResult,
    DriveSyncResponse,
    SyncErrorCode,
    SyncFileStatus,
)
from app.schemas.receipt import ReceiptUploadResponse
from app.services.gemini import ReceiptParseError, extract_receipt_from_pdf
from app.services.google_drive_client import download_file, list_pdf_files
from app.services.receipt import (
    compute_pdf_hash,
    find_by_pdf_hash,
    get_existing_drive_file_ids,
    process_extracted_receipt,
    validate_pdf_bytes,
)

logger = logging.getLogger(__name__)
```

Everything from `async def _process_single_file(db: AsyncSession, df: DriveFile) -> DriveSyncFileResult:` down to the end of the file (including Task 1's savepoint change) stays exactly as-is — only the imports above it change.

- [ ] **Step 3: Run tests**

Run: `docker compose exec api pytest tests/test_drive_sync.py -v`
Expected: all PASS unchanged (patch targets `app.services.google_drive.list_pdf_files` / `.download_file` / `.extract_receipt_from_pdf` / `._process_single_file` all still resolve, since these names are still attributes of the `google_drive` module via the imports in Step 2).

- [ ] **Step 4: Run full suite and lint**

Run: `docker compose exec api pytest && docker compose exec api ruff check app/ && docker compose exec api ruff format --check app/`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/google_drive_client.py backend/app/services/google_drive.py
git commit -m "refactor(P2-4): split Google Drive API adapter from sync orchestration"
```

---

## Task 5: P2-2 + P2-3 + P2-4b — Consolidate enrichment, move OFF rate-limiting into the adapter, fix Gemini matching bug

This is the largest task. It rewrites `services/openfoodfacts.py` (add `search_many`, owning the client lifecycle and rate limiting), `services/gemini.py` (`match_products_with_off` loses its dead `supermarket_name` param and its `NameError` risk), and `services/enrichment.py` (one `_enrich` core shared by both public entry points, keyed by `product.id` instead of `product.name`, plus a single-query supermarket-hint lookup replacing the N+1 loop).

**Files:**
- Modify: `backend/app/services/openfoodfacts.py`
- Modify: `backend/app/services/gemini.py`
- Modify: `backend/app/services/enrichment.py`
- Test: `backend/tests/test_enrichment.py` (rewrite `TestMatchProductsWithOff`, `TestEnrichProducts`, `TestEnrichPending`; add `TestSearchMany`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `enrich_products(db, products, supermarket_hint=None) -> EnrichmentResult` and `enrich_pending(db, limit=10) -> EnrichmentResult` keep their exact public signatures (Task 6 depends on `enrich_products` still existing with this signature). `openfoodfacts.search_many(names: dict[uuid.UUID, str]) -> dict[uuid.UUID, list[OFFCandidate]]` is new. `gemini.match_products_with_off(candidates: dict[str, list[OFFCandidate]]) -> dict[str, str | None]` drops its `supermarket_name` parameter.

- [ ] **Step 1: Add `search_many` to the Open Food Facts adapter**

In `backend/app/services/openfoodfacts.py`, add `import uuid` to the imports, and add this function after `search_products`:

```python
async def search_many(names: dict[uuid.UUID, str]) -> dict[uuid.UUID, list[OFFCandidate]]:
    """Search Open Food Facts for several products, respecting the rate limit between calls.

    Owns the HTTP client lifecycle and the inter-request delay so callers don't have to.
    Returns only the ids that had at least one candidate.
    """
    results: dict[uuid.UUID, list[OFFCandidate]] = {}
    async with httpx.AsyncClient(timeout=OFF_TIMEOUT) as client:
        for i, (key, name) in enumerate(names.items()):
            if i > 0:
                await asyncio.sleep(REQUEST_DELAY)
            candidates = await search_products(name, client=client)
            if candidates:
                results[key] = candidates
    return results
```

- [ ] **Step 2: Write tests for `search_many` first**

Add to `backend/tests/test_enrichment.py` (needs `search_many` added to the `from app.services.openfoodfacts import ...` import):

```python
class TestSearchMany:
    @patch("app.services.openfoodfacts.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.services.openfoodfacts.httpx.AsyncClient")
    async def test_searches_all_and_respects_rate_limit(
        self, mock_client_cls: MagicMock, mock_sleep: AsyncMock
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = _off_api_response([_off_product()])
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        id_a, id_b = uuid.uuid4(), uuid.uuid4()
        result = await search_many({id_a: "cacahuete", id_b: "leche"})

        assert set(result.keys()) == {id_a, id_b}
        assert mock_sleep.call_count == 1  # delay only between requests, not before the first

    @patch("app.services.openfoodfacts.httpx.AsyncClient")
    async def test_omits_ids_with_no_candidates(self, mock_client_cls: MagicMock):
        empty_response = MagicMock()
        empty_response.json.return_value = _off_api_response([])
        empty_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=empty_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await search_many({uuid.uuid4(): "xyznonexistent"})

        assert result == {}
```

- [ ] **Step 3: Run test to verify it fails, then verify it passes**

Run: `docker compose exec api pytest tests/test_enrichment.py::TestSearchMany -v`
Expected: FAIL first (`ImportError`/`AttributeError`, `search_many` doesn't exist yet) — confirm Step 1 hasn't landed, or re-run after Step 1 to confirm PASS.

- [ ] **Step 4: Fix `match_products_with_off`'s dead parameter and `NameError` risk**

Replace the matching section of `backend/app/services/gemini.py` (from `MATCHING_PROMPT_TEMPLATE` to the end of `match_products_with_off`) with:

```python
MATCHING_PROMPT_TEMPLATE = (
    "You are matching abbreviated Spanish supermarket receipt product names "
    "to Open Food Facts product entries.\n\n"
    "For each product below, choose the BEST matching Open Food Facts candidate "
    "or respond with null if none is a good match.\n"
    "Respond ONLY with a JSON object mapping each product name to the chosen "
    "EAN code (string) or null. Example: "
    '{{"LECHE ENTERA": "8480000123456", "UNKNOWN PRODUCT": null}}\n\n'
    "Products:\n{products_block}"
)


async def match_products_with_off(
    candidates: dict[str, list[OFFCandidate]],
) -> dict[str, str | None]:
    """Use Gemini to select the best OFF match for each product. Returns empty dict on error."""
    if not candidates:
        return {}

    lines = []
    for i, (name, options) in enumerate(candidates.items(), 1):
        options_str = ", ".join(
            f'{{"code": "{o.code}", "name": "{o.product_name}"}}' for o in options
        )
        lines.append(f"{i}. {name} -> [{options_str}]")

    products_block = "\n".join(lines)
    prompt = MATCHING_PROMPT_TEMPLATE.format(products_block=products_block)

    client = _get_client()
    try:
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
    except GeminiAPIError:
        logger.warning("Gemini API error during OFF matching", exc_info=True)
        return {}

    try:
        return json.loads(response.text)
    except (json.JSONDecodeError, ValueError):
        logger.error("Failed to parse Gemini matching response: %s", response.text)
        return {}
```

This removes the unused `supermarket_name` parameter (production callers already encode the hint into the candidate dict's keys instead — the one real mechanism) and moves `client = _get_client()` outside the `try` so `response` is always bound before the second `try` block references `response.text`.

- [ ] **Step 5: Update `TestMatchProductsWithOff` for the dropped parameter**

In `backend/tests/test_enrichment.py`, change both calls:

```python
        result = await match_products_with_off(candidates, supermarket_name="MERCADONA")
```

to:

```python
        result = await match_products_with_off(candidates)
```

(two occurrences: `test_returns_matched_codes` and `test_returns_empty_on_gemini_error`).

- [ ] **Step 6: Rewrite `enrichment.py`'s core**

Replace `backend/app/services/enrichment.py` in full with:

```python
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
from app.schemas.enrichment import EnrichmentResult, OFFCandidate
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
```

(`get_or_create_many` and `services/common.py` are created in Task 7 — if executing tasks out of order, do Task 7's Step 1 first, or land this import as a forward reference and run Task 7 immediately after. As planned, Tasks run in this document's order, but `_assign_categories`'s call to `get_or_create_many` needs `services/common.py` to exist; move Task 7 Step 1 (creating `services/common.py`) earlier if executing task-by-task with tests passing at each commit — see note below.)

> **Ordering note:** `services/common.py` (with `get_or_create_many`) must exist before this step, since `_assign_categories` now calls it. Do Task 7's Step 1 (create `services/common.py`) as a **prerequisite sub-step here**, before this file rewrite, so tests pass at the end of this task. Task 7 will then only need to update `receipt.py`'s `_resolve_products` to use it too.

- [ ] **Step 7: Rewrite the enrichment tests to mock `search_many` instead of `search_products`**

In `backend/tests/test_enrichment.py`, replace `TestEnrichProducts` and `TestEnrichPending` in full with:

```python
class TestEnrichProducts:
    @patch("app.services.enrichment.match_products_with_off", new_callable=AsyncMock)
    @patch("app.services.enrichment.search_many", new_callable=AsyncMock)
    async def test_enriches_product_successfully(
        self, mock_search: AsyncMock, mock_match: AsyncMock, db_session: AsyncSession
    ):
        product = await _create_product(db_session)

        candidate = OFFCandidate(
            code="8480000340313",
            product_name="Cacahuete tostado 0% sal",
            categories="Cacahuetes,Frutos secos",
            image_url="https://images.openfoodfacts.org/example.jpg",
        )
        mock_search.return_value = {product.id: [candidate]}
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
    @patch("app.services.enrichment.search_many", new_callable=AsyncMock)
    async def test_sets_synced_at_when_no_match(
        self, mock_search: AsyncMock, mock_match: AsyncMock, db_session: AsyncSession
    ):
        product = await _create_product(db_session)

        mock_search.return_value = {product.id: [OFFCandidate(code="999", product_name="X")]}
        mock_match.return_value = {"CACAHUETE SIN SAL": None}

        result = await enrich_products(db_session, [product])

        assert result.processed == 1
        assert result.enriched == 0
        assert result.not_found == 1
        assert product.off_code is None
        assert product.off_synced_at is not None

    @patch("app.services.enrichment.match_products_with_off", new_callable=AsyncMock)
    @patch("app.services.enrichment.search_many", new_callable=AsyncMock)
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
    @patch("app.services.enrichment.search_many", new_callable=AsyncMock)
    async def test_gemini_failure_leaves_synced_at_null(
        self, mock_search: AsyncMock, mock_match: AsyncMock, db_session: AsyncSession
    ):
        product = await _create_product(db_session)

        mock_search.return_value = {
            product.id: [OFFCandidate(code="8480000340313", product_name="Cacahuete")]
        }
        mock_match.return_value = {}  # Gemini failed

        result = await enrich_products(db_session, [product])

        assert result.failed is True
        assert product.off_synced_at is None

    @patch("app.services.enrichment.match_products_with_off", new_callable=AsyncMock)
    @patch("app.services.enrichment.search_many", new_callable=AsyncMock)
    async def test_no_off_results_sets_synced_at(
        self, mock_search: AsyncMock, mock_match: AsyncMock, db_session: AsyncSession
    ):
        product = await _create_product(db_session)
        mock_search.return_value = {}  # OFF returned nothing

        result = await enrich_products(db_session, [product])

        assert result.processed == 1
        assert result.enriched == 0
        assert result.not_found == 1
        assert product.off_synced_at is not None
        mock_match.assert_not_called()  # No candidates = no Gemini call

    @patch("app.services.enrichment.match_products_with_off", new_callable=AsyncMock)
    @patch("app.services.enrichment.search_many", new_callable=AsyncMock)
    async def test_assigns_categories_from_off(
        self, mock_search: AsyncMock, mock_match: AsyncMock, db_session: AsyncSession
    ):
        product = await _create_product(db_session)

        mock_search.return_value = {
            product.id: [
                OFFCandidate(
                    code="8480000340313",
                    product_name="Cacahuete tostado 0% sal",
                    categories="Cacahuetes,Frutos secos",
                    image_url="https://example.com/img.jpg",
                )
            ]
        }
        mock_match.return_value = {"CACAHUETE SIN SAL": "8480000340313"}

        await enrich_products(db_session, [product])

        result = await db_session.execute(select(Category).order_by(Category.name))
        cats = result.scalars().all()
        assert len(cats) == 2
        cat_names = {c.name for c in cats}
        assert cat_names == {"Cacahuetes", "Frutos secos"}

        await db_session.refresh(product, ["categories"])
        product_cat_names = {c.name for c in product.categories}
        assert product_cat_names == {"Cacahuetes", "Frutos secos"}

    @patch("app.services.enrichment.match_products_with_off", new_callable=AsyncMock)
    @patch("app.services.enrichment.search_many", new_callable=AsyncMock)
    async def test_reuses_existing_categories(
        self, mock_search: AsyncMock, mock_match: AsyncMock, db_session: AsyncSession
    ):
        existing_cat = Category(name="Cacahuetes")
        db_session.add(existing_cat)
        await db_session.flush()

        product = await _create_product(db_session)

        mock_search.return_value = {
            product.id: [
                OFFCandidate(
                    code="8480000340313",
                    product_name="Cacahuete tostado 0% sal",
                    categories="Cacahuetes,Frutos secos",
                )
            ]
        }
        mock_match.return_value = {"CACAHUETE SIN SAL": "8480000340313"}

        await enrich_products(db_session, [product])

        result = await db_session.execute(select(Category))
        all_cats = result.scalars().all()
        assert len(all_cats) == 2

        await db_session.refresh(product, ["categories"])
        assert any(c.id == existing_cat.id for c in product.categories)


class TestEnrichPending:
    @patch("app.services.enrichment.match_products_with_off", new_callable=AsyncMock)
    @patch("app.services.enrichment.search_many", new_callable=AsyncMock)
    async def test_selects_unsynced_products(
        self, mock_search: AsyncMock, mock_match: AsyncMock, db_session: AsyncSession
    ):
        product = await _create_product_with_ticket(db_session)

        mock_search.return_value = {
            product.id: [
                OFFCandidate(
                    code="8480000340313",
                    product_name="Cacahuete tostado 0% sal",
                    categories="Cacahuetes",
                    image_url="https://example.com/img.jpg",
                )
            ]
        }
        mock_match.return_value = {"CACAHUETE SIN SAL (MERCADONA)": "8480000340313"}

        result = await enrich_pending(db_session, limit=10)

        assert result.processed == 1
        assert result.enriched == 1
        assert product.off_code == "8480000340313"

    @patch("app.services.enrichment.match_products_with_off", new_callable=AsyncMock)
    @patch("app.services.enrichment.search_many", new_callable=AsyncMock)
    async def test_passes_supermarket_name_to_gemini(
        self, mock_search: AsyncMock, mock_match: AsyncMock, db_session: AsyncSession
    ):
        product = await _create_product_with_ticket(
            db_session, product_name="LECHE ENTERA", supermarket_name="MERCADONA"
        )

        mock_search.return_value = {product.id: [OFFCandidate(code="848", product_name="Leche entera")]}
        mock_match.return_value = {"LECHE ENTERA (MERCADONA)": "848"}

        await enrich_pending(db_session, limit=10)

        call_args = mock_match.call_args
        candidates = call_args[0][0] if call_args[0] else call_args[1]["candidates"]
        assert "LECHE ENTERA (MERCADONA)" in candidates
```

- [ ] **Step 8: Update the single-enrich endpoint test target**

`TestEnrichEndpoints.test_single_enrich` currently patches `app.api.products.enrich_products` — this now needs to patch `app.api.products.enrich_one` instead (the router is updated to call `enrich_one` in Task 6; if Task 6 hasn't landed yet, leave this test patch as `enrich_products` for now and revisit in Task 6's own test step — do not change it here to avoid a temporarily-broken patch target).

- [ ] **Step 9: Run tests**

Run: `docker compose exec api pytest tests/test_enrichment.py -v`
Expected: all PASS.

- [ ] **Step 10: Run full suite and lint**

Run: `docker compose exec api pytest && docker compose exec api ruff check app/ && docker compose exec api ruff format --check app/`

- [ ] **Step 11: Commit**

```bash
git add backend/app/services/openfoodfacts.py backend/app/services/gemini.py backend/app/services/enrichment.py backend/tests/test_enrichment.py
git commit -m "refactor(P2-2,P2-3,P2-4): consolidate enrichment, move OFF rate-limit into adapter, fix Gemini matching bug"
```

---

## Task 6: P2-1 — Move category add/remove and force-reenrich logic to the service layer

**Files:**
- Modify: `backend/app/services/product.py`
- Modify: `backend/app/api/products.py`
- Test: `backend/tests/test_enrichment.py` (`TestEnrichEndpoints.test_single_enrich` patch target)

**Interfaces:**
- Consumes: `enrich_one(db, product)` from Task 5.
- Produces: `product_service.add_category(db, product, category)`, `product_service.remove_category(db, product, category)`, exceptions `product_service.CategoryAlreadyAssignedError`, `product_service.CategoryNotAssignedError`.

- [ ] **Step 1: Add the service functions**

In `backend/app/services/product.py`, add the import `from app.models.category import Category` and append:

```python
class CategoryAlreadyAssignedError(Exception):
    """Raised when a product already has the category being added."""


class CategoryNotAssignedError(Exception):
    """Raised when trying to remove a category the product doesn't have."""


async def add_category(db: AsyncSession, product: Product, category: Category) -> Product:
    await db.refresh(product, ["categories"])
    if category in product.categories:
        raise CategoryAlreadyAssignedError
    product.categories.append(category)
    await db.flush()
    await db.refresh(product)
    return product


async def remove_category(db: AsyncSession, product: Product, category: Category) -> None:
    await db.refresh(product, ["categories"])
    if category not in product.categories:
        raise CategoryNotAssignedError
    product.categories.remove(category)
    await db.flush()
```

- [ ] **Step 2: Thin out the router**

In `backend/app/api/products.py`, change the import block to:

```python
from app.services import category as category_service
from app.services import product as product_service
from app.services.enrichment import enrich_one, enrich_pending, reset_failed_enrichments
```

Replace `single_enrich_product`:

```python
@router.post("/{product_id}/enrich", response_model=EnrichmentResult)
async def single_enrich_product(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_gemini),
):
    product = await product_service.get_by_id(db, product_id)
    if not product:
        raise not_found("Producto")
    return await enrich_one(db, product)
```

Replace `add_category_to_product` and `remove_category_from_product`:

```python
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

    try:
        return await product_service.add_category(db, product, category)
    except product_service.CategoryAlreadyAssignedError:
        raise conflict("El producto ya tiene esta categoría asignada")


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

    try:
        await product_service.remove_category(db, product, category)
    except product_service.CategoryNotAssignedError:
        raise not_found("Categoría no asignada al producto")
```

- [ ] **Step 3: Fix the enrich-endpoint test's patch target**

In `backend/tests/test_enrichment.py`, change `TestEnrichEndpoints.test_single_enrich`:

```python
    @patch("app.api.products.enrich_products", new_callable=AsyncMock)
    async def test_single_enrich(
```

to:

```python
    @patch("app.api.products.enrich_one", new_callable=AsyncMock)
    async def test_single_enrich(
```

(the body of the test is unchanged).

- [ ] **Step 4: Run tests**

Run: `docker compose exec api pytest tests/test_enrichment.py tests/test_products.py -v`
Expected: all PASS.

- [ ] **Step 5: Run full suite and lint**

Run: `docker compose exec api pytest && docker compose exec api ruff check app/ && docker compose exec api ruff format --check app/`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/product.py backend/app/api/products.py backend/tests/test_enrichment.py
git commit -m "refactor(P2-1): move category assignment and force-reenrich logic to service layer"
```

---

## Task 7: P2-5 — Move Ticket queries into ticket.py, add shared get_or_create_many, fix supermarket lookup

**Note:** `services/common.py` (Step 1 below) was already created as a prerequisite during Task 5 if tasks were executed strictly in order (see the ordering note in Task 5, Step 6). If it already exists, skip Step 1 and proceed from Step 2.

**Files:**
- Create: `backend/app/services/common.py`
- Modify: `backend/app/services/ticket.py`
- Modify: `backend/app/services/receipt.py`
- Modify: `backend/app/services/supermarket.py`
- Modify: `backend/app/services/google_drive.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `services.common.get_or_create_many(db, model, names, factory) -> tuple[dict[str, ModelT], set[str]]`. `ticket_service.find_by_pdf_hash`, `ticket_service.find_by_invoice_number`, `ticket_service.get_existing_drive_file_ids` (moved from `receipt.py`). `supermarket_service.get_by_name`.

- [ ] **Step 1: Create the shared batch-resolution helper**

Create `backend/app/services/common.py`:

```python
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

ModelT = TypeVar("ModelT", bound=DeclarativeBase)


async def get_or_create_many(
    db: AsyncSession,
    model: type[ModelT],
    names: list[str],
    factory: Callable[[str], ModelT],
) -> tuple[dict[str, ModelT], set[str]]:
    """Batch find-or-create rows of `model` by their unique `name` column.

    Returns (name -> instance map covering both existing and new rows, set of
    names that were newly created). Flushes if anything was created.
    """
    unique_names = list(dict.fromkeys(names))
    if not unique_names:
        return {}, set()

    result = await db.execute(select(model).where(model.name.in_(unique_names)))
    existing = {row.name: row for row in result.scalars().all()}

    created_names = {name for name in unique_names if name not in existing}
    for name in created_names:
        instance = factory(name)
        db.add(instance)
        existing[name] = instance

    if created_names:
        await db.flush()

    return existing, created_names
```

- [ ] **Step 2: Move Ticket queries into `ticket.py`**

Replace `backend/app/services/ticket.py` in full with:

```python
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ticket import Ticket
from app.schemas.ticket import TicketCreate, TicketUpdate


async def create(db: AsyncSession, data: TicketCreate) -> Ticket:
    ticket = Ticket(**data.model_dump())
    db.add(ticket)
    await db.flush()
    return ticket


async def get_by_id(db: AsyncSession, ticket_id: uuid.UUID) -> Ticket | None:
    return await db.get(Ticket, ticket_id)


async def get_list(db: AsyncSession, skip: int = 0, limit: int = 20) -> tuple[list[Ticket], int]:
    total = await db.scalar(select(func.count()).select_from(Ticket))
    result = await db.execute(select(Ticket).order_by(Ticket.date.desc()).offset(skip).limit(limit))
    return list(result.scalars().all()), total or 0


async def find_by_pdf_hash(db: AsyncSession, pdf_hash: str) -> Ticket | None:
    result = await db.execute(
        select(Ticket).options(selectinload(Ticket.supermarket)).where(Ticket.pdf_hash == pdf_hash)
    )
    return result.scalar_one_or_none()


async def find_by_invoice_number(db: AsyncSession, invoice_number: str) -> Ticket | None:
    result = await db.execute(
        select(Ticket)
        .options(selectinload(Ticket.supermarket))
        .where(Ticket.invoice_number == invoice_number)
    )
    return result.scalar_one_or_none()


async def get_existing_drive_file_ids(db: AsyncSession, candidate_ids: list[str]) -> set[str]:
    """Return the subset of candidate_ids that already exist in the database."""
    if not candidate_ids:
        return set()
    result = await db.execute(
        select(Ticket.drive_file_id).where(Ticket.drive_file_id.in_(candidate_ids))
    )
    return {row[0] for row in result.all()}


async def update(db: AsyncSession, ticket_id: uuid.UUID, data: TicketUpdate) -> Ticket | None:
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(ticket, field, value)
    await db.flush()
    await db.refresh(ticket)
    return ticket


async def delete(db: AsyncSession, ticket_id: uuid.UUID) -> bool:
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        return False
    await db.delete(ticket)
    await db.flush()
    return True
```

- [ ] **Step 3: Add `get_by_name` to `supermarket.py`**

In `backend/app/services/supermarket.py`, add after `create`:

```python
async def get_by_name(db: AsyncSession, name: str) -> Supermarket | None:
    result = await db.execute(select(Supermarket).where(Supermarket.name == name))
    return result.scalar_one_or_none()
```

- [ ] **Step 4: Slim `receipt.py` down to receipt-specific orchestration**

Replace `backend/app/services/receipt.py` in full with:

```python
import hashlib
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.schemas.line_item import LineItemCreate
from app.schemas.receipt import ExtractedReceipt, ReceiptUploadResponse
from app.schemas.supermarket import SupermarketCreate
from app.schemas.ticket import TicketCreate
from app.services import line_item as line_item_service
from app.services import supermarket as supermarket_service
from app.services import ticket as ticket_service
from app.services.common import get_or_create_many

logger = logging.getLogger(__name__)

MAX_PDF_SIZE = 10 * 1024 * 1024  # 10 MB


class InvalidPdfError(ValueError):
    """Raised when uploaded bytes are not a valid, size-bounded PDF."""


def validate_pdf_bytes(pdf_bytes: bytes) -> None:
    """Raise InvalidPdfError if pdf_bytes is not a valid PDF within the size limit."""
    if not pdf_bytes.startswith(b"%PDF"):
        raise InvalidPdfError("not_pdf")
    if len(pdf_bytes) > MAX_PDF_SIZE:
        raise InvalidPdfError("too_large")


def compute_pdf_hash(pdf_bytes: bytes) -> str:
    return hashlib.sha256(pdf_bytes).hexdigest()


async def _find_or_create_supermarket(
    db: AsyncSession, name: str, locality: str | None
) -> "Supermarket":
    existing = await supermarket_service.get_by_name(db, name)
    if existing:
        return existing
    return await supermarket_service.create(db, SupermarketCreate(name=name, locality=locality))


async def _resolve_products(
    db: AsyncSession, names: list[str]
) -> tuple[dict[str, Product], int, int]:
    """Batch find-or-create products. Returns (name→product map, created, matched)."""
    products_map, created_names = await get_or_create_many(
        db, Product, names, lambda name: Product(name=name)
    )
    matched = sum(1 for n in names if n not in created_names)
    created = sum(1 for n in names if n in created_names)
    return products_map, created, matched


async def process_extracted_receipt(
    db: AsyncSession,
    data: ExtractedReceipt,
    pdf_hash: str,
    drive_file_id: str | None = None,
) -> ReceiptUploadResponse:
    if data.invoice_number:
        duplicate = await ticket_service.find_by_invoice_number(db, data.invoice_number)
        if duplicate:
            logger.info(
                "Duplicate ticket (invoice_number=%s): %s", data.invoice_number, duplicate.id
            )
            return ReceiptUploadResponse.duplicate_from(duplicate)

    supermarket = await _find_or_create_supermarket(
        db, data.supermarket_name, data.supermarket_locality
    )

    ticket = await ticket_service.create(
        db,
        TicketCreate(
            date=data.date,
            supermarket_id=supermarket.id,
            total=data.total,
            invoice_number=data.invoice_number,
            pdf_hash=pdf_hash,
            drive_file_id=drive_file_id,
        ),
    )

    product_names = [item.product_name for item in data.line_items]
    products_map, products_created, products_matched = await _resolve_products(db, product_names)

    for item in data.line_items:
        await line_item_service.create(
            db,
            ticket.id,
            LineItemCreate(
                product_id=products_map[item.product_name].id,
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
            ),
        )

    logger.info(
        "Ticket %s saved: %d new products, %d matched, %d line items",
        ticket.id,
        products_created,
        products_matched,
        len(data.line_items),
    )
    return ReceiptUploadResponse(
        ticket_id=ticket.id,
        supermarket=supermarket.name,
        date=ticket.date,
        total=ticket.total,
        products_created=products_created,
        products_matched=products_matched,
        line_items_count=len(data.line_items),
    )
```

(The `"Supermarket"` string-quoted return annotation on `_find_or_create_supermarket` needs `from app.models.supermarket import Supermarket` added to the imports, not a `TYPE_CHECKING`-only import, since it's only used as a type hint at module level here too — add it as a normal import.)

- [ ] **Step 5: Update `google_drive.py`'s imports**

In `backend/app/services/google_drive.py`, change:

```python
from app.services.receipt import (
    compute_pdf_hash,
    find_by_pdf_hash,
    get_existing_drive_file_ids,
    process_extracted_receipt,
    validate_pdf_bytes,
)
```

to:

```python
from app.services.receipt import InvalidPdfError, compute_pdf_hash, process_extracted_receipt, validate_pdf_bytes
from app.services.ticket import find_by_pdf_hash, get_existing_drive_file_ids
```

And update `_process_single_file`'s validation call (it currently does `validation_error = validate_pdf_bytes(pdf_bytes)` then checks truthiness — `validate_pdf_bytes` now raises instead of returning a string):

```python
async def _process_single_file(db: AsyncSession, df: DriveFile) -> DriveSyncFileResult:
    """Download, validate, extract, and persist a single Drive PDF."""
    pdf_bytes = await download_file(df.id)

    try:
        validate_pdf_bytes(pdf_bytes)
    except InvalidPdfError as exc:
        detail = (
            "El archivo no es un PDF válido"
            if str(exc) == "not_pdf"
            else "El archivo excede el tamaño máximo de 10 MB"
        )
        return DriveSyncFileResult(
            file_name=df.name,
            status=SyncFileStatus.ERROR,
            error_code=SyncErrorCode.INVALID_PDF,
            error_detail=detail,
        )

    pdf_hash = compute_pdf_hash(pdf_bytes)

    existing = await find_by_pdf_hash(db, pdf_hash)
    if existing:
        logger.info("Duplicate PDF hash for '%s', ticket=%s", df.name, existing.id)
        return DriveSyncFileResult(
            file_name=df.name,
            status=SyncFileStatus.DUPLICATE,
            detail=ReceiptUploadResponse.duplicate_from(existing),
        )

    extracted = await extract_receipt_from_pdf(pdf_bytes)
    response = await process_extracted_receipt(db, extracted, pdf_hash, drive_file_id=df.id)

    result_status = SyncFileStatus.DUPLICATE if response.duplicate else SyncFileStatus.PROCESSED
    return DriveSyncFileResult(file_name=df.name, status=result_status, detail=response)
```

(This also folds in P2-10's fix for this call site — see Task 9, which then only needs to touch `api/tickets.py`.)

- [ ] **Step 6: Run tests**

Run: `docker compose exec api pytest tests/test_receipts.py tests/test_drive_sync.py tests/test_tickets.py tests/test_supermarkets.py -v`
Expected: all PASS (no test in these files directly imports/patches the moved private functions, so no test file needs edits for this step).

- [ ] **Step 7: Run full suite and lint**

Run: `docker compose exec api pytest && docker compose exec api ruff check app/ && docker compose exec api ruff format --check app/`

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/common.py backend/app/services/ticket.py backend/app/services/receipt.py backend/app/services/supermarket.py backend/app/services/google_drive.py
git commit -m "refactor(P2-5): move ticket queries to ticket service, add get_or_create_many, use supermarket_service"
```

---

## Task 8: P2-6 — Config-gating consistency

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/app/api/google_drive.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Produces: `settings.gemini_enabled`, `settings.google_drive_enabled` properties; `require_google_drive` dependency (mirrors `require_gemini`).

- [ ] **Step 1: Add the properties to `Settings`**

In `backend/app/core/config.py`, add after the `_derive_test_url` validator (before `model_config`):

```python
    @property
    def gemini_enabled(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def google_drive_enabled(self) -> bool:
        return bool(self.google_drive_credentials_path and self.google_drive_folder_id)
```

- [ ] **Step 2: Add `require_google_drive` and use the new properties**

Replace `backend/app/api/dependencies.py` in full with:

```python
from fastapi import HTTPException, status

from app.core.config import settings


def require_gemini() -> None:
    """Raise 503 if Gemini API key is not configured."""
    if not settings.gemini_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de extracción no configurado (falta GEMINI_API_KEY)",
        )


def require_google_drive() -> None:
    """Raise 503 if Google Drive is not configured."""
    if not settings.google_drive_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de Google Drive no configurado "
            "(faltan GOOGLE_DRIVE_CREDENTIALS_PATH o GOOGLE_DRIVE_FOLDER_ID)",
        )
```

- [ ] **Step 3: Simplify the Drive sync router**

Replace `backend/app/api/google_drive.py` in full with:

```python
import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_gemini, require_google_drive
from app.core.database import get_db
from app.schemas.google_drive import DriveSyncResponse
from app.services import google_drive as google_drive_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tickets/drive", tags=["tickets"])


@router.post(
    "/sync",
    response_model=DriveSyncResponse,
    status_code=status.HTTP_200_OK,
    summary="Sincronizar tickets PDF desde Google Drive",
)
async def sync_from_drive(
    db: AsyncSession = Depends(get_db),
    _gemini: None = Depends(require_gemini),
    _drive: None = Depends(require_google_drive),
):
    return await google_drive_service.sync_drive_folder(db)
```

(This also folds in the P3 import-style fix and tag-consistency fix for this router — see Task 11.)

- [ ] **Step 4: Update `main.py`'s startup warnings**

In `backend/app/main.py`, change:

```python
if not settings.gemini_api_key:
    logger.warning("GEMINI_API_KEY not set — PDF ticket extraction will be unavailable")

if not settings.google_drive_credentials_path or not settings.google_drive_folder_id:
    logger.warning("Google Drive not configured — Drive sync will be unavailable")
```

to:

```python
if not settings.gemini_enabled:
    logger.warning("GEMINI_API_KEY not set — PDF ticket extraction will be unavailable")

if not settings.google_drive_enabled:
    logger.warning("Google Drive not configured — Drive sync will be unavailable")
```

- [ ] **Step 5: Run tests**

Run: `docker compose exec api pytest tests/test_drive_sync.py tests/test_receipts.py -v`
Expected: all PASS unchanged — `test_sync_missing_gemini_key` and `test_sync_missing_drive_config` still get the same detail messages, and the dependency order (`require_gemini` before `require_google_drive`) still makes `test_sync_missing_gemini_key` (which leaves Drive config valid) fail on the Gemini check first.

- [ ] **Step 6: Run full suite and lint**

Run: `docker compose exec api pytest && docker compose exec api ruff check app/ && docker compose exec api ruff format --check app/`

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/config.py backend/app/api/dependencies.py backend/app/api/google_drive.py backend/app/main.py
git commit -m "refactor(P2-6): consistent config-gating via Settings properties and require_google_drive"
```

---

## Task 9: P2-8 — Schema convention fixes (Field(default=None), max_length)

**Files:**
- Modify: `backend/app/schemas/ticket.py`
- Modify: `backend/app/schemas/line_item.py`

- [ ] **Step 1: Fix `TicketCreate` and `TicketUpdate`**

Replace `backend/app/schemas/ticket.py`'s `TicketCreate` and `TicketUpdate` with:

```python
class TicketCreate(BaseModel):
    date: datetime.date
    supermarket_id: uuid.UUID
    total: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    invoice_number: str | None = Field(default=None, max_length=100)
    pdf_hash: str | None = Field(default=None, max_length=64)
    drive_file_id: str | None = Field(default=None, max_length=100)


class TicketUpdate(BaseModel):
    date: datetime.date | None = Field(default=None)
    supermarket_id: uuid.UUID | None = Field(default=None)
    total: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
```

- [ ] **Step 2: Fix `LineItemUpdate`**

Replace `backend/app/schemas/line_item.py`'s `LineItemUpdate` with:

```python
class LineItemUpdate(BaseModel):
    product_id: uuid.UUID | None = Field(default=None)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=3)
    unit_price: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    line_total: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
```

- [ ] **Step 3: Run tests**

Run: `docker compose exec api pytest tests/test_tickets.py tests/test_receipts.py tests/test_drive_sync.py -v`
Expected: all PASS (test fixtures use invoice numbers/hashes well under the new limits).

- [ ] **Step 4: Run full suite and lint**

Run: `docker compose exec api pytest && docker compose exec api ruff check app/ && docker compose exec api ruff format --check app/`

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/ticket.py backend/app/schemas/line_item.py
git commit -m "fix(P2-8): Field(default=None) and max_length convention on ticket/line_item Update/Create schemas"
```

---

## Task 10: P2-10 — Typed exception instead of Spanish string from `api/tickets.py`

**Files:**
- Modify: `backend/app/api/tickets.py`

(`services/receipt.py::validate_pdf_bytes` and `services/google_drive.py`'s corresponding call site were already converted to raise/catch `InvalidPdfError` in Task 7, Steps 4–5. This task only needs to update the remaining caller, `api/tickets.py`.)

- [ ] **Step 1: Update the upload router**

In `backend/app/api/tickets.py`, add `from app.services.receipt import InvalidPdfError` to the imports (alongside the existing `receipt` imports), and replace:

```python
    validation_error = validate_pdf_bytes(pdf_bytes)
    if validation_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=validation_error,
        )
```

with:

```python
    try:
        validate_pdf_bytes(pdf_bytes)
    except InvalidPdfError as exc:
        detail = (
            "El archivo no es un PDF válido"
            if str(exc) == "not_pdf"
            else "El archivo excede el tamaño máximo de 10 MB"
        )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)
```

- [ ] **Step 2: Run tests**

Run: `docker compose exec api pytest tests/test_receipts.py -v`
Expected: all PASS — `test_upload_rejects_spoofed_pdf` still gets `"PDF válido"` in the detail.

- [ ] **Step 3: Run full suite and lint**

Run: `docker compose exec api pytest && docker compose exec api ruff check app/ && docker compose exec api ruff format --check app/`

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/tickets.py
git commit -m "fix(P2-10): raise typed InvalidPdfError instead of returning Spanish strings from the service layer"
```

---

## Task 11: P3 — Import style consistency + naming fixes

**Files:**
- Modify: `backend/app/api/tickets.py`
- Modify: `backend/app/api/products.py`
- Test: `backend/tests/test_receipts.py` (8 patch targets move)

(`api/google_drive.py` was already fixed in Task 8, Step 3, including its tag.)

- [ ] **Step 1: Fix `api/tickets.py`'s imports**

Change:

```python
from app.services import ticket as ticket_service
from app.services.gemini import ReceiptParseError, extract_receipt_from_pdf
from app.services.receipt import (
    compute_pdf_hash,
    find_by_pdf_hash,
    process_extracted_receipt,
    validate_pdf_bytes,
)
```

to:

```python
from app.services import gemini as gemini_service
from app.services import receipt as receipt_service
from app.services import ticket as ticket_service
from app.services.gemini import ReceiptParseError
from app.services.receipt import InvalidPdfError
```

(Exception classes stay imported directly by name — that's normal Python style, not a services-import violation; only the *functions* move to qualified module access.) Then update every call site in the file:
- `extract_receipt_from_pdf(pdf_bytes)` → `gemini_service.extract_receipt_from_pdf(pdf_bytes)`
- `validate_pdf_bytes(pdf_bytes)` → `receipt_service.validate_pdf_bytes(pdf_bytes)`
- `find_by_pdf_hash(db, pdf_hash)` → `ticket_service.find_by_pdf_hash(db, pdf_hash)` (already qualified via `ticket_service`, just drop the now-unused bare import)
- `process_extracted_receipt(db, extracted, pdf_hash)` → `receipt_service.process_extracted_receipt(db, extracted, pdf_hash)`

- [ ] **Step 2: Update the 8 test patch targets in `test_receipts.py`**

Every occurrence of `@patch("app.api.tickets.extract_receipt_from_pdf", new_callable=AsyncMock)` moves to `@patch("app.services.gemini.extract_receipt_from_pdf", new_callable=AsyncMock)` (patching the function where it's defined works regardless of how the caller imports the module). Use a single find-and-replace across the file for the string `"app.api.tickets.extract_receipt_from_pdf"` → `"app.services.gemini.extract_receipt_from_pdf"` (8 occurrences: `test_upload_success`, `test_upload_creates_entities_in_db`, `test_upload_gemini_api_error`, `test_upload_gemini_parse_error`, `test_upload_reuses_existing_supermarket`, `test_upload_reuses_existing_products`, `test_duplicate_same_pdf_skips_gemini`, `test_duplicate_same_invoice_different_pdf`).

- [ ] **Step 3: Fix `api/products.py`'s imports and rename the reset endpoint handler**

Change:

```python
from app.services import category as category_service
from app.services import product as product_service
from app.services.enrichment import enrich_one, enrich_pending, reset_failed_enrichments
```

to:

```python
from app.services import category as category_service
from app.services import enrichment as enrichment_service
from app.services import product as product_service
```

Update call sites: `enrich_pending(db, limit=limit)` → `enrichment_service.enrich_pending(db, limit=limit)`; `reset_failed_enrichments(db)` → `enrichment_service.reset_failed_enrichments(db)`; `enrich_one(db, product)` → `enrichment_service.enrich_one(db, product)`.

Rename the handler (the `_endpoint` suffix existed only to avoid colliding with the now-removed bare `reset_failed_enrichments` import):

```python
@router.post("/enrich/reset", response_model=ResetResult)
async def reset_failed_enrichments(
    db: AsyncSession = Depends(get_db),
):
    count = await enrichment_service.reset_failed_enrichments(db)
    return ResetResult(reset=count)
```

- [ ] **Step 4: Update the enrich-endpoint test patch targets**

In `backend/tests/test_enrichment.py`:
- `@patch("app.api.products.enrich_pending", ...)` → `@patch("app.services.enrichment.enrich_pending", ...)` (in `TestEnrichEndpoints.test_batch_enrich`)
- `@patch("app.api.products.enrich_one", ...)` → `@patch("app.services.enrichment.enrich_one", ...)` (in `TestEnrichEndpoints.test_single_enrich`, from Task 6)

- [ ] **Step 5: Run tests**

Run: `docker compose exec api pytest tests/test_receipts.py tests/test_enrichment.py tests/test_products.py -v`
Expected: all PASS.

- [ ] **Step 6: Run full suite and lint**

Run: `docker compose exec api pytest && docker compose exec api ruff check app/ && docker compose exec api ruff format --check app/`

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/tickets.py backend/app/api/products.py backend/tests/test_receipts.py backend/tests/test_enrichment.py
git commit -m "style(P3): import services as modules consistently, drop redundant _endpoint suffix"
```

---

## Task 12: P3 — Relocate integration DTOs to their adapters, move duplicate_from mapper into ticket service

**Files:**
- Modify: `backend/app/schemas/enrichment.py` → move `OFFCandidate` out
- Modify: `backend/app/services/openfoodfacts.py` → `OFFCandidate` now lives here
- Modify: `backend/app/schemas/google_drive.py` → move `DriveFile` out
- Modify: `backend/app/services/google_drive_client.py` → `DriveFile` now lives here
- Modify: `backend/app/schemas/receipt.py` → drop `duplicate_from` and the `TYPE_CHECKING` import of `Ticket`
- Modify: `backend/app/services/ticket.py` → add `receipt_from_duplicate`

This is purely a "move code, update imports" task — no behavior changes, so no new tests; existing tests must keep passing unchanged.

- [ ] **Step 1: Move `OFFCandidate` into the OFF adapter**

In `backend/app/services/openfoodfacts.py`, add near the top (after the existing imports):

```python
from pydantic import BaseModel


class OFFCandidate(BaseModel):
    """A product candidate returned by Open Food Facts search."""

    code: str
    product_name: str
    categories: str | None = None
    image_url: str | None = None
```

In `backend/app/schemas/enrichment.py`, remove the `OFFCandidate` class and add `from app.services.openfoodfacts import OFFCandidate` — **wait**, this creates a schemas→services import, which is backwards (services should depend on schemas, not vice versa). Since `EnrichmentResult`/`ResetResult` in this same file don't need `OFFCandidate` at all (only `enrichment.py` and `gemini.py` use it), the correct fix is: every importer of `OFFCandidate` (`app/services/enrichment.py`, `app/services/gemini.py`) changes its import from `from app.schemas.enrichment import OFFCandidate` to `from app.services.openfoodfacts import OFFCandidate`, and `backend/app/schemas/enrichment.py` simply drops the `OFFCandidate` class entirely (keeping only `EnrichmentResult` and `ResetResult`).

- [ ] **Step 2: Update `OFFCandidate` importers**

In `backend/app/services/enrichment.py`, change:

```python
from app.schemas.enrichment import EnrichmentResult, OFFCandidate
```

to:

```python
from app.schemas.enrichment import EnrichmentResult
from app.services.openfoodfacts import OFFCandidate, search_many
```

(drop the separate `from app.services.openfoodfacts import search_many` line added in Task 5, merge it here).

In `backend/app/services/gemini.py`, change:

```python
from app.schemas.enrichment import OFFCandidate
```

to:

```python
from app.services.openfoodfacts import OFFCandidate
```

In `backend/tests/test_enrichment.py`, change:

```python
from app.schemas.enrichment import EnrichmentResult, OFFCandidate
```

to:

```python
from app.schemas.enrichment import EnrichmentResult
from app.services.openfoodfacts import OFFCandidate
```

- [ ] **Step 3: Move `DriveFile` into the Drive client adapter**

In `backend/app/services/google_drive_client.py`, replace the import `from app.schemas.google_drive import DriveFile` and add instead:

```python
from pydantic import BaseModel


class DriveFile(BaseModel):
    """Metadata of a file in Google Drive."""

    id: str
    name: str
```

In `backend/app/schemas/google_drive.py`, remove the `DriveFile` class.

In `backend/app/services/google_drive.py`, change:

```python
from app.schemas.google_drive import (
    DriveFile,
    DriveSyncFileResult,
    DriveSyncResponse,
    SyncErrorCode,
    SyncFileStatus,
)
...
from app.services.google_drive_client import download_file, list_pdf_files
```

to:

```python
from app.schemas.google_drive import (
    DriveSyncFileResult,
    DriveSyncResponse,
    SyncErrorCode,
    SyncFileStatus,
)
...
from app.services.google_drive_client import DriveFile, download_file, list_pdf_files
```

In `backend/tests/test_drive_sync.py`, change `from app.schemas.google_drive import DriveFile` to `from app.services.google_drive_client import DriveFile`.

- [ ] **Step 4: Move `duplicate_from` into `ticket.py`**

In `backend/app/schemas/receipt.py`, remove the `TYPE_CHECKING` block and the `duplicate_from` static method from `ReceiptUploadResponse`, leaving just the plain field declarations.

In `backend/app/services/ticket.py`, add:

```python
from app.schemas.receipt import ReceiptUploadResponse


def receipt_from_duplicate(ticket: Ticket) -> ReceiptUploadResponse:
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

Update every call site of `ReceiptUploadResponse.duplicate_from(...)`:
- `backend/app/services/receipt.py`: `ReceiptUploadResponse.duplicate_from(duplicate)` → `ticket_service.receipt_from_duplicate(duplicate)`
- `backend/app/services/google_drive.py`: `ReceiptUploadResponse.duplicate_from(existing)` → needs `from app.services import ticket as ticket_service` added, then `ticket_service.receipt_from_duplicate(existing)`

- [ ] **Step 5: Run tests**

Run: `docker compose exec api pytest`
Expected: all PASS unchanged (pure relocation, no behavior change).

- [ ] **Step 6: Run lint**

Run: `docker compose exec api ruff check app/ && docker compose exec api ruff format --check app/`

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/ backend/app/services/ backend/tests/test_enrichment.py backend/tests/test_drive_sync.py
git commit -m "refactor(P3): relocate integration DTOs to their adapters, move duplicate-ticket mapper to ticket service"
```

---

## Task 13: P3 — Singletons via functools.lru_cache, redundant refresh cleanup, config.py reorg

**Files:**
- Modify: `backend/app/services/gemini.py`
- Modify: `backend/app/services/google_drive_client.py`
- Modify: `backend/app/services/product.py`
- Modify: `backend/app/core/config.py`

- [ ] **Step 1: Replace the `global`-based Gemini client singleton**

In `backend/app/services/gemini.py`, add `from functools import lru_cache` to the imports and replace:

```python
_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client
```

with:

```python
@lru_cache(maxsize=1)
def _get_client() -> genai.Client:
    return genai.Client(api_key=settings.gemini_api_key)
```

- [ ] **Step 2: Replace the `global`-based Drive service singleton**

In `backend/app/services/google_drive_client.py`, add `from functools import lru_cache` and replace:

```python
_service = None


def _get_service():
    """Lazily initialize the Google Drive API service (singleton)."""
    global _service
    if _service is None:
        credentials = service_account.Credentials.from_service_account_file(
            settings.google_drive_credentials_path, scopes=SCOPES
        )
        _service = build("drive", "v3", credentials=credentials)
    return _service
```

with:

```python
@lru_cache(maxsize=1)
def _get_service():
    """Lazily initialize the Google Drive API service (singleton)."""
    credentials = service_account.Credentials.from_service_account_file(
        settings.google_drive_credentials_path, scopes=SCOPES
    )
    return build("drive", "v3", credentials=credentials)
```

> **Test note:** any test that changes `settings.gemini_api_key` or `settings.google_drive_credentials_path` mid-suite and expects a fresh client next call would need `_get_client.cache_clear()` / `_get_service.cache_clear()`. Check: no existing test calls `_get_client()`/`_get_service()` more than once with different settings values expecting a different client instance back (`test_drive_sync.py`'s tests all mock `list_pdf_files`/`download_file` directly, never invoking the real `_get_service()`; `test_receipts.py`/`test_enrichment.py` mock `_get_client` itself via `@patch("app.services.gemini._get_client")`, replacing the whole function, so caching is irrelevant there). No test changes needed.

- [ ] **Step 3: Remove the redundant refresh in `product.py`**

In `backend/app/services/product.py`, change:

```python
async def create(db: AsyncSession, data: ProductCreate) -> Product:
    product = Product(**data.model_dump())
    db.add(product)
    await db.flush()
    await db.refresh(product)
    return product
```

to:

```python
async def create(db: AsyncSession, data: ProductCreate) -> Product:
    product = Product(**data.model_dump())
    db.add(product)
    await db.flush()
    return product
```

(SQLAlchemy 2.0's asyncpg dialect populates server-generated defaults like `created_at`/`updated_at` via `RETURNING` on flush already — this matches every other entity's `create()`, none of which refresh.)

- [ ] **Step 4: Reorganize `config.py`**

Replace `backend/app/core/config.py` in full with:

```python
from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://grocery:grocery_dev@db:5432/grocery_receipt"
    database_url_test: str = ""
    secret_key: str
    debug: bool = False
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash-lite"
    google_drive_credentials_path: str = ""
    google_drive_folder_id: str = ""
    gemini_batch_limit: int = 0

    model_config = {"env_file": ".env"}

    @model_validator(mode="after")
    def _derive_test_url(self) -> "Settings":
        if not self.database_url_test:
            base = self.database_url.rstrip("/")
            self.database_url_test = base.rsplit("/", 1)[0] + "/grocery_receipt_test"
        return self

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def google_drive_enabled(self) -> bool:
        return bool(self.google_drive_credentials_path and self.google_drive_folder_id)


settings = Settings()
```

(All field declarations are now grouped together, followed by `model_config`, then the validator, then the two properties from Task 8.)

- [ ] **Step 5: Run tests**

Run: `docker compose exec api pytest`
Expected: all PASS.

- [ ] **Step 6: Run lint**

Run: `docker compose exec api ruff check app/ && docker compose exec api ruff format --check app/`

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/gemini.py backend/app/services/google_drive_client.py backend/app/services/product.py backend/app/core/config.py
git commit -m "refactor(P3): lru_cache singletons, drop redundant refresh, reorganize Settings"
```

---

## Task 14: P3 — Health endpoint readiness status, shared pagination dependency

**Files:**
- Modify: `backend/app/api/health.py`
- Test: `backend/tests/test_health.py`
- Create: `backend/app/schemas/pagination.py` gets a new `Pagination` dependency (or add to `api/dependencies.py`)
- Modify: `backend/app/api/categories.py`, `products.py`, `supermarkets.py`, `tickets.py`

- [ ] **Step 1: Check the current health test first**

Read `backend/tests/test_health.py` before editing (`Read` it) to see what it currently asserts, then update its status-code assertion for the "disconnected" branch alongside the implementation change below (the two must land together since this is a genuine behavior change: a disconnected DB must now return a non-200 status).

- [ ] **Step 2: Make `/health` return 503 when the DB is unreachable**

Replace `backend/app/api/health.py` with:

```python
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

router = APIRouter()


@router.get("/health")
async def health_check(response: Response, db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "disconnected"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if db_status == "connected" else "degraded", "db": db_status}
```

Update `backend/tests/test_health.py`'s existing "connected" test to still expect `200` and `"status": "ok"` (unchanged), and add:

```python
async def test_health_reports_degraded_when_db_unreachable(client: AsyncClient, monkeypatch):
    from app.core import database as database_module

    async def broken_execute(*args, **kwargs):
        raise ConnectionError("db down")

    monkeypatch.setattr(database_module.AsyncSession, "execute", broken_execute)

    resp = await client.get("/health")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["db"] == "disconnected"
```

(Exact monkeypatch target depends on what `test_health.py` currently imports — adjust to whatever fixture/pattern the existing file already uses for the `client` fixture; the key behavioral assertion is `resp.status_code == 503` and `body["db"] == "disconnected"`.)

- [ ] **Step 3: Add a shared pagination dependency**

In `backend/app/schemas/pagination.py`, add below `PaginatedResponse`:

```python
from dataclasses import dataclass

from fastapi import Query


@dataclass
class Pagination:
    skip: int
    limit: int


def pagination_params(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> Pagination:
    return Pagination(skip=skip, limit=limit)
```

- [ ] **Step 4: Use it in the four list endpoints**

In each of `backend/app/api/categories.py`, `products.py`, `supermarkets.py`, `tickets.py`, change the list handler from:

```python
async def list_categories(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await category_service.get_list(db, skip=skip, limit=limit)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)
```

to:

```python
async def list_categories(
    pagination: Pagination = Depends(pagination_params),
    db: AsyncSession = Depends(get_db),
):
    items, total = await category_service.get_list(db, skip=pagination.skip, limit=pagination.limit)
    return PaginatedResponse(items=items, total=total, skip=pagination.skip, limit=pagination.limit)
```

(same pattern for `list_products`, `list_supermarkets`, `list_tickets` — add `from app.schemas.pagination import Pagination, PaginatedResponse, pagination_params` to each file's imports, dropping the now-unused `Query` import where nothing else in that file needs it — check each file first).

- [ ] **Step 5: Run tests**

Run: `docker compose exec api pytest`
Expected: all PASS — pagination behavior (query params, response shape) is unchanged, only how each router obtains `skip`/`limit` changed.

- [ ] **Step 6: Run lint**

Run: `docker compose exec api ruff check app/ && docker compose exec api ruff format --check app/`

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/health.py backend/tests/test_health.py backend/app/schemas/pagination.py backend/app/api/categories.py backend/app/api/products.py backend/app/api/supermarkets.py backend/app/api/tickets.py
git commit -m "fix(P3): health endpoint reports 503 when DB is unreachable; extract shared pagination dependency"
```

---

## Final verification (after all 14 tasks)

- [ ] Run the full suite one more time end to end: `docker compose exec api pytest -v`
- [ ] Run `docker compose exec api ruff check app/` and `docker compose exec api ruff format --check app/`
- [ ] Diff-review the branch against `main` for anything left inconsistent (e.g. stray unused imports from the several import-style changes)
- [ ] Confirm nothing from the explicitly out-of-scope list (P1-3, P1-4, P2-7, docker-compose exposure, `products.name` uniqueness, etc.) was touched
