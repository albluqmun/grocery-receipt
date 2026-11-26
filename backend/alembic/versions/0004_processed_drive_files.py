"""processed drive files registry

Adds a new table only (no changes to existing data) so the Drive sync can skip
files already resolved as duplicates or invalid PDFs.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-26

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processed_drive_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("drive_file_id", sa.String(length=100), nullable=False),
        sa.Column("outcome", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("drive_file_id"),
    )


def downgrade() -> None:
    op.drop_table("processed_drive_files")
