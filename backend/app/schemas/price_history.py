from datetime import date as _date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class PriceHistoryEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: _date
    supermarket_name: str
    unit_price: Decimal
