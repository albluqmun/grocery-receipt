import datetime
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class TicketCreate(BaseModel):
    date: datetime.date
    supermarket_id: uuid.UUID
    total: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class TicketUpdate(BaseModel):
    date: datetime.date | None = None
    supermarket_id: uuid.UUID | None = None
    total: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)


class TicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    date: datetime.date
    supermarket_id: uuid.UUID
    total: Decimal
    created_at: datetime.datetime
    updated_at: datetime.datetime
