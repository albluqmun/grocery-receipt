"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-03-25

This is a baseline migration. Tables are created by Base.metadata.create_all()
at startup. This revision exists so that Alembic knows the current state of the
database and future migrations can build on top of it.
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
