import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SupermarketCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    locality: str | None = Field(default=None, max_length=200)


class SupermarketUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    locality: str | None = Field(default=None, max_length=200)


class SupermarketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    locality: str | None
    created_at: datetime
    updated_at: datetime
