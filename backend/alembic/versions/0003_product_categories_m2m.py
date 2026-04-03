"""product categories many-to-many

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-30

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_categories",
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("product_id", "category_id"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_product_categories_category_id", "product_categories", ["category_id"])

    op.drop_constraint("products_category_id_fkey", "products", type_="foreignkey")
    op.drop_index("ix_products_category_id", table_name="products")
    op.drop_column("products", "category_id")
    op.drop_column("products", "off_categories")


def downgrade() -> None:
    op.add_column("products", sa.Column("off_categories", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("category_id", sa.Uuid(), nullable=True))
    op.create_index("ix_products_category_id", "products", ["category_id"])
    op.create_foreign_key(
        "products_category_id_fkey", "products", "categories", ["category_id"], ["id"]
    )
    op.drop_index("ix_product_categories_category_id", table_name="product_categories")
    op.drop_table("product_categories")
