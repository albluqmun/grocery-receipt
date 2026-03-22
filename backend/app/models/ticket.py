import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Ticket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tickets"

    date: Mapped[date]
    supermarket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("supermarkets.id"), index=True)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    invoice_number: Mapped[str | None] = mapped_column(String(100), unique=True)
    pdf_hash: Mapped[str | None] = mapped_column(String(64), unique=True)

    supermarket = relationship("Supermarket", lazy="selectin")
    lines = relationship(
        "LineItem", back_populates="ticket", cascade="all, delete-orphan", lazy="selectin"
    )
