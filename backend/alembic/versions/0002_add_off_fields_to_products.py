"""add OFF fields to products

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-29

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("off_code", sa.String(50), nullable=True))
    op.add_column("products", sa.Column("off_name", sa.String(300), nullable=True))
    op.add_column("products", sa.Column("off_image_url", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("off_categories", sa.Text(), nullable=True))
    op.add_column(
        "products",
        sa.Column("off_synced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("products", "off_synced_at")
    op.drop_column("products", "off_categories")
    op.drop_column("products", "off_image_url")
    op.drop_column("products", "off_name")
    op.drop_column("products", "off_code")
