"""Added the audit log

Revision ID: 646857d0ee21
Revises: dd10df590cb2
Create Date: 2026-10-07 13:02:58.330033
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "646857d0ee21"
down_revision: str | Sequence[str] | None = "dd10df590cb2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this migration; migrations only go forward (development rules, 10)."""
    op.create_table(
        "audit_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=True),
        sa.Column("tool", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column(
            "action_class",
            sa.Enum(
                "read",
                "write-internal",
                "external",
                "destructive",
                name="action_class",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                "expired",
                "done",
                "failed",
                "denied",
                name="entry_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "audit_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("entry_id", sa.Uuid(), nullable=False),
        sa.Column("table_name", sa.String(), nullable=False),
        sa.Column("object_id", sa.Uuid(), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["audit_entries.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_audit_changes_entry_id"), "audit_changes", ["entry_id"], unique=False
    )
