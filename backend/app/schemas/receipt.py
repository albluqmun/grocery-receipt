import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from app.models.ticket import Ticket


def _fit_numeric(value: Decimal, max_digits: int, places: int) -> Decimal:
    """Round to `places` decimals and ensure it fits Numeric(max_digits, places)."""
    if not value.is_finite():
        raise ValueError("el valor debe ser un número finito")
    if abs(value) >= Decimal(10) ** (max_digits - places):
        raise ValueError(f"el valor excede el rango de Numeric({max_digits}, {places})")
    return value.quantize(Decimal(1).scaleb(-places))


class ExtractedLineItem(BaseModel):
    """Line item extracted from a receipt by AI.

    Signs are not restricted here: discount lines (negative or zero amounts) are
    dropped later by the receipt service instead of failing the whole receipt.
    """

    product_name: str = Field(min_length=1, max_length=300)  # products.name
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal

    @field_validator("quantity")
    @classmethod
    def _check_quantity(cls, v: Decimal) -> Decimal:
        return _fit_numeric(v, 10, 3)

    @field_validator("unit_price", "line_total")
    @classmethod
    def _check_money(cls, v: Decimal) -> Decimal:
        return _fit_numeric(v, 10, 2)


class ExtractedReceipt(BaseModel):
    """Structured data extracted from a receipt PDF by AI."""

    supermarket_name: str = Field(min_length=1, max_length=200)  # supermarkets.name
    supermarket_locality: str | None = Field(default=None, max_length=200)
    invoice_number: str | None = Field(default=None, max_length=100)  # tickets.invoice_number
    date: datetime.date
    total: Decimal
    line_items: list[ExtractedLineItem]

    @field_validator("total")
    @classmethod
    def _check_total(cls, v: Decimal) -> Decimal:
        v = _fit_numeric(v, 10, 2)
        if v <= 0:
            raise ValueError("el total debe ser mayor que 0")
        return v


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
