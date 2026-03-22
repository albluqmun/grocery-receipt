from pydantic import BaseModel


class PaginatedResponse[T](BaseModel):
    items: list[T]
    total: int
    skip: int
    limit: int
