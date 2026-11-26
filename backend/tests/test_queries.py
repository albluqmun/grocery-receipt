import datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.line_item import LineItem
from app.models.product import Product
from app.models.supermarket import Supermarket
from app.models.ticket import Ticket
from app.services import line_item as line_item_service

API = "/api/v1"


async def _all_pages(client: AsyncClient, url: str, page_size: int = 2) -> list[str]:
    ids: list[str] = []
    skip = 0
    while True:
        sep = "&" if "?" in url else "?"
        resp = await client.get(f"{url}{sep}skip={skip}&limit={page_size}")
        assert resp.status_code == 200
        items = resp.json()["items"]
        if not items:
            return ids
        ids.extend(i["id"] for i in items)
        skip += page_size


# --- R18/C7: no implicit back-reference loading ---


async def test_back_references_do_not_load_implicitly(db_session: AsyncSession):
    sm = Supermarket(name="Mercadona")
    prod = Product(name="Leche")
    cat = Category(name="Lácteos")
    prod.categories.append(cat)
    db_session.add_all([sm, prod])
    await db_session.flush()
    ticket = Ticket(date=datetime.date(2026, 1, 1), supermarket_id=sm.id, total=Decimal("1"))
    db_session.add(ticket)
    await db_session.flush()
    line = LineItem(
        ticket_id=ticket.id,
        product_id=prod.id,
        quantity=Decimal("1"),
        unit_price=Decimal("1"),
        line_total=Decimal("1"),
    )
    db_session.add(line)
    await db_session.commit()
    line_id, cat_id = line.id, cat.id
    db_session.expire_all()

    loaded_line = await db_session.get(LineItem, line_id)
    assert loaded_line.product.name == "Leche"  # still eager
    with pytest.raises(InvalidRequestError):
        _ = loaded_line.ticket
    loaded_cat = await db_session.get(Category, cat_id)
    with pytest.raises(InvalidRequestError):
        _ = loaded_cat.products


async def test_delete_category_with_products(client: AsyncClient, db_session: AsyncSession):
    prod = Product(name="Leche")
    prod.categories.append(Category(name="Lácteos"))
    db_session.add(prod)
    await db_session.commit()
    cat_id, prod_id = prod.categories[0].id, prod.id
    assert (await client.delete(f"{API}/categories/{cat_id}")).status_code == 204
    db_session.expire_all()
    resp = await client.get(f"{API}/products/{prod_id}")
    assert resp.json()["categories"] == []


# --- C13/R14: stable ordering with tied sort keys ---


async def test_pagination_stable_with_ties(client: AsyncClient, db_session: AsyncSession):
    sm = Supermarket(name="Mercadona")
    db_session.add(sm)
    db_session.add_all([Product(name="Igual") for _ in range(7)])
    db_session.add_all([Category(name=f"c{i}") for i in range(3)])
    await db_session.flush()
    db_session.add_all(
        [
            Ticket(date=datetime.date(2026, 1, 1), supermarket_id=sm.id, total=Decimal("1"))
            for _ in range(7)
        ]
    )
    await db_session.commit()

    for path in ("products", "tickets"):
        ids = await _all_pages(client, f"{API}/{path}")
        assert len(ids) == 7
        assert len(set(ids)) == 7, f"{path}: duplicated/missing rows between pages"


async def test_line_items_pagination_stable_with_ties(db_session: AsyncSession):
    sm = Supermarket(name="Mercadona")
    prod = Product(name="Leche")
    db_session.add_all([sm, prod])
    await db_session.flush()
    ticket = Ticket(date=datetime.date(2026, 1, 1), supermarket_id=sm.id, total=Decimal("1"))
    db_session.add(ticket)
    await db_session.flush()
    # Same created_at for every line (tie on the sort key)
    ts = datetime.datetime(2026, 1, 1)
    db_session.add_all(
        [
            LineItem(
                ticket_id=ticket.id,
                product_id=prod.id,
                quantity=Decimal("1"),
                unit_price=Decimal("1"),
                line_total=Decimal("1"),
                created_at=ts,
            )
            for _ in range(7)
        ]
    )
    await db_session.commit()
    ids: list[str] = []
    for skip in range(0, 8, 2):
        page, total = await line_item_service.get_list(db_session, ticket.id, skip=skip, limit=2)
        assert total == 7
        ids.extend(str(line.id) for line in page)
    assert len(ids) == len(set(ids)) == 7


async def test_tied_rows_ordered_by_id(client: AsyncClient, db_session: AsyncSession):
    db_session.add_all([Product(name="Igual") for _ in range(5)])
    await db_session.commit()
    resp = await client.get(f"{API}/products?limit=10")
    ids = [i["id"] for i in resp.json()["items"]]
    assert ids == sorted(ids)


# --- C12/R15: LIKE wildcards in search are literal ---


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("%", ["100% natural"]),
        ("_", ["agua_mineral"]),
        ("\\", ["ruta\\dir"]),
        ("100%", ["100% natural"]),
        ("a_m", ["agua_mineral"]),
    ],
)
async def test_search_escapes_like_wildcards(
    client: AsyncClient, db_session: AsyncSession, query: str, expected: list[str]
):
    db_session.add_all(
        [Product(name=n) for n in ["100% natural", "agua_mineral", "ruta\\dir", "aguaXmineral"]]
    )
    await db_session.commit()
    resp = await client.get(f"{API}/products", params={"q": query})
    assert resp.status_code == 200
    body = resp.json()
    assert sorted(i["name"] for i in body["items"]) == sorted(expected)
    assert body["total"] == len(expected)
