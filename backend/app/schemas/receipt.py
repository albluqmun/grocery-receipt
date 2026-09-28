import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class ExtractedLineItem(BaseModel):
    """Line item extracted from a receipt by AI."""

    product_name: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


class ExtractedReceipt(BaseModel):
    """Structured data extracted from a receipt PDF by AI."""

    supermarket_name: str
    supermarket_locality: str | None = None
    invoice_number: str | None = None
    date: datetime.date
    total: Decimal
    line_items: list[ExtractedLineItem]


class ReceiptUploadResponse(BaseModel):
    """Response after processing a receipt PDF."""

    ticket_id: UUID
    supermarket: str = Field(examples=["MERCADONA"])
    date: datetime.date = Field(examples=["2026-03-21"])
    total: Decimal = Field(examples=["62.00"])
    products_created: int = Field(examples=[26])
    products_matched: int = Field(examples=[0])
    line_items_count: int = Field(examples=[26])
    duplicate: bool = False
