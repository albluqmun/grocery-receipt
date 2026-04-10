import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.category import CategoryRead


class ProductCategoryAdd(BaseModel):
    category_id: uuid.UUID


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    brand: str | None = Field(default=None, max_length=200)


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    brand: str | None = Field(default=None, max_length=200)


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    brand: str | None
    categories: list[CategoryRead]
    off_code: str | None
    off_name: str | None
    off_image_url: str | None
    off_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime
