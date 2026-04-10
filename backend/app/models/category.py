from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Category(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "categories"

    name: Mapped[str] = mapped_column(String(200), unique=True)
    external_id: Mapped[str | None] = mapped_column(String(100))

    products = relationship(
        "Product", secondary="product_categories", back_populates="categories", lazy="selectin"
    )
