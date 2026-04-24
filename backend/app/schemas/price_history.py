from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class PriceHistoryEntry(BaseModel):
    date: date
    supermarket_name: str
    unit_price: Decimal
