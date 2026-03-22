import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class LineItemCreate(BaseModel):
    product_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=10, decimal_places=3)
    unit_price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    line_total: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class LineItemUpdate(BaseModel):
    product_id: uuid.UUID | None = None
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=3)
    unit_price: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    line_total: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)


class LineItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID
    product_id: uuid.UUID
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    created_at: datetime
    updated_at: datetime
