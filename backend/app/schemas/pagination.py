from dataclasses import dataclass

from fastapi import Query
from pydantic import BaseModel


class PaginatedResponse[T](BaseModel):
    items: list[T]
    total: int
    skip: int
    limit: int


@dataclass
class Pagination:
    skip: int
    limit: int


def pagination_params(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> Pagination:
    return Pagination(skip=skip, limit=limit)
