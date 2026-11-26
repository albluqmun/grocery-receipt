"""add indexes for product name, ticket date, line item lookups and OFF sync

Revision ID: 0005
Revises: 0003
Create Date: 2026-11-26

NOTE: if the ingestion PR (0004, processed_drive_files) merges first, rebase and
set down_revision to "0004" so there is a single head.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_products_name", "products", ["name"])
    op.create_index("ix_products_off_synced_at", "products", ["off_synced_at"])
    op.create_index("ix_tickets_date", "tickets", ["date"])
    op.create_index("ix_line_items_product_id_ticket_id", "line_items", ["product_id", "ticket_id"])


def downgrade() -> None:
    op.drop_index("ix_line_items_product_id_ticket_id", table_name="line_items")
    op.drop_index("ix_tickets_date", table_name="tickets")
    op.drop_index("ix_products_off_synced_at", table_name="products")
    op.drop_index("ix_products_name", table_name="products")
