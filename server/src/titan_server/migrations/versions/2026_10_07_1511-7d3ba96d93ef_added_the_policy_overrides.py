"""Added the policy overrides

Revision ID: 7d3ba96d93ef
Revises: 0ec0b12122fd
Create Date: 2026-10-07 15:11:57.253614
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7d3ba96d93ef"
down_revision: str | Sequence[str] | None = "0ec0b12122fd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this migration; migrations only go forward (development rules, 10)."""
    op.create_table(
        "policy_overrides",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "domain",
            sa.Enum("tasks", name="domain", native_enum=False, create_constraint=True),
            nullable=False,
        ),
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
            "mode",
            sa.Enum(
                "auto",
                "auto-undo",
                "confirm",
                "deny",
                name="mode",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action_class NOT IN ('external', 'destructive')"
            " OR mode IN ('confirm', 'deny')",
            name="policy_overrides_floor",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "domain", "action_class"),
    )
