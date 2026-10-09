"""Removed the approved status and indexed pending requests

Revision ID: b0b00ff7627f
Revises: af66cb59e74a
Create Date: 2026-10-07 16:34:16.089559
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b0b00ff7627f"
down_revision: str | Sequence[str] | None = "af66cb59e74a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this migration; migrations only go forward (development rules, 10)."""
    # An approved call ends done or failed (decision #123). No entry was ever
    # approved, nothing set it, so no row needs to change. The column keeps
    # its length: rejected is as long as approved was.
    op.drop_constraint("entry_status", "audit_entries", type_="check")
    op.create_check_constraint(
        "entry_status",
        "audit_entries",
        "status IN ('pending', 'rejected', 'expired', 'done', 'failed', 'denied')",
    )
    # The list of pending requests reads them by user, in paging order
    # (decision #124).
    op.create_index(
        "ix_audit_entries_pending",
        "audit_entries",
        ["user_id", "created_at", "id"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
