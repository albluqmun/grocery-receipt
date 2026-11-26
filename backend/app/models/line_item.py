import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class LineItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "line_items"
    __table_args__ = (Index("ix_line_items_product_id_ticket_id", "product_id", "ticket_id"),)

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    ticket = relationship("Ticket", back_populates="lines", lazy="selectin")
    product = relationship("Product", lazy="selectin")
