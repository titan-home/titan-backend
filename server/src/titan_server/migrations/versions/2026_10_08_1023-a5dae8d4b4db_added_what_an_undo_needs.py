"""Added what an undo needs: the trash of tasks and the undo columns of entries

Revision ID: a5dae8d4b4db
Revises: b0b00ff7627f
Create Date: 2026-10-08 10:23:41.200339
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a5dae8d4b4db"
down_revision: str | Sequence[str] | None = "b0b00ff7627f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this migration; migrations only go forward (development rules, 10)."""
    op.add_column("audit_entries", sa.Column("undoable", sa.Boolean(), nullable=True))
    # Every entry written before this is a call of create_task, the only tool,
    # which can be undone (decision #130).
    op.execute("UPDATE audit_entries SET undoable = true")
    op.alter_column("audit_entries", "undoable", nullable=False)
    op.add_column(
        "audit_entries", sa.Column("undoes_entry_id", sa.Uuid(), nullable=True)
    )
    op.create_unique_constraint(None, "audit_entries", ["undoes_entry_id"])
    op.create_foreign_key(
        None, "audit_entries", "audit_entries", ["undoes_entry_id"], ["id"]
    )
    # An undo has no mode (decision #131).
    op.alter_column(
        "audit_entries", "mode", existing_type=sa.VARCHAR(length=9), nullable=True
    )
    op.add_column(
        "tasks", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
