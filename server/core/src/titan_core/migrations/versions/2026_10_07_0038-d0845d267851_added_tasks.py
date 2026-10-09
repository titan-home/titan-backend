"""Added tasks

Revision ID: d0845d267851
Revises: c0ce4557a591
Create Date: 2026-10-07 00:38:47.464065
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d0845d267851"
down_revision: str | Sequence[str] | None = "c0ce4557a591"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this migration; migrations only go forward (development rules, 10)."""
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "done",
                "cancelled",
                name="task_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
