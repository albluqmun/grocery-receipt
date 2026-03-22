import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    external_id: str | None = Field(default=None, max_length=100)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    external_id: str | None = Field(default=None, max_length=100)


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    external_id: str | None
    created_at: datetime
    updated_at: datetime
