"""Added the version counter to tasks

Revision ID: dd10df590cb2
Revises: 20ec545b36fd
Create Date: 2026-10-07 12:34:50.061324
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "dd10df590cb2"
down_revision: str | Sequence[str] | None = "20ec545b36fd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this migration; migrations only go forward (development rules, 10)."""
    op.add_column(
        "tasks", sa.Column("version", sa.Integer(), server_default="1", nullable=False)
    )
