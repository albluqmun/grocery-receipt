from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ProcessedDriveFile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Drive file already handled by the sync without producing a ticket.

    Lets the sync skip duplicates and invalid PDFs instead of re-downloading them
    (and re-sending them to Gemini) on every run.
    """

    __tablename__ = "processed_drive_files"

    drive_file_id: Mapped[str] = mapped_column(String(100), unique=True)
    outcome: Mapped[str] = mapped_column(String(30))
