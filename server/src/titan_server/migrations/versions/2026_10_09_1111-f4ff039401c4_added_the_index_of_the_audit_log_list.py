"""Added the index of the audit log list

Revision ID: f4ff039401c4
Revises: a5dae8d4b4db
Create Date: 2026-10-09 11:11:39.754019
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f4ff039401c4"
down_revision: str | Sequence[str] | None = "a5dae8d4b4db"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this migration; migrations only go forward (development rules, 10)."""
    op.create_index(
        "ix_audit_entries_user_created",
        "audit_entries",
        ["user_id", "created_at", "id"],
        unique=False,
    )
