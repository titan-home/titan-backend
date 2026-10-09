"""Added the domain to audit entries

Revision ID: af66cb59e74a
Revises: 7d3ba96d93ef
Create Date: 2026-10-07 16:36:39.062960
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "af66cb59e74a"
down_revision: str | Sequence[str] | None = "7d3ba96d93ef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this migration; migrations only go forward (development rules, 10)."""
    op.add_column(
        "audit_entries",
        sa.Column(
            "domain",
            sa.Enum("tasks", name="domain", native_enum=False, create_constraint=True),
            nullable=True,
        ),
    )
    # Every entry written before this is a call of create_task, the only tool.
    op.execute("UPDATE audit_entries SET domain = 'tasks'")
    op.alter_column("audit_entries", "domain", nullable=False)
