import datetime
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


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


class TicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    date: datetime.date
    supermarket_id: uuid.UUID
    total: Decimal
    drive_file_id: str | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
