"""Added the mode to audit entries

Revision ID: 0ec0b12122fd
Revises: 646857d0ee21
Create Date: 2026-10-07 14:37:04.439651
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0ec0b12122fd"
down_revision: str | Sequence[str] | None = "646857d0ee21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this migration; migrations only go forward (development rules, 10)."""
    op.add_column(
        "audit_entries",
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
            nullable=True,
        ),
    )
    # Every entry written before the policy is a call that ran at once, in the
    # default mode of its class (decision #38): no other class had a tool.
    op.execute(
        "UPDATE audit_entries SET mode = CASE action_class"
        " WHEN 'read' THEN 'auto' ELSE 'auto-undo' END"
    )
    op.alter_column("audit_entries", "mode", nullable=False)
