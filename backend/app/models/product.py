from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

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

    categories = relationship(
        "Category", secondary=product_categories, back_populates="products", lazy="selectin"
    )
