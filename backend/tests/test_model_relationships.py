"""Regression tests pinning ORM-level delete behavior for one-to-many/M2M relationships.

Without passive_deletes, SQLAlchemy loads the child collection on parent delete
and issues an UPDATE/DELETE per child before the DB's own ON DELETE behavior
ever runs — slower, and it changes what actually rejects the delete (an ORM
NOT NULL violation instead of the DB's FK constraint). These tests assert the
mapper configuration directly, since the end-to-end HTTP behavior (409) is
identical either way and wouldn't catch a regression here.
"""

from sqlalchemy import inspect as sa_inspect

from app.models.category import Category
from app.models.product import Product
from app.models.supermarket import Supermarket


def test_supermarket_tickets_relationship_uses_passive_deletes():
    rel = sa_inspect(Supermarket).relationships["tickets"]
    assert rel.passive_deletes == "all"


def test_product_line_items_relationship_uses_passive_deletes():
    rel = sa_inspect(Product).relationships["line_items"]
    assert rel.passive_deletes == "all"


def test_category_products_relationship_uses_passive_deletes():
    rel = sa_inspect(Category).relationships["products"]
    assert rel.passive_deletes is True
