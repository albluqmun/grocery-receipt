from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Supermarket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "supermarkets"

    name: Mapped[str] = mapped_column(String(200), unique=True)
    locality: Mapped[str | None] = mapped_column(String(200))
