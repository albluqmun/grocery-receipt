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
