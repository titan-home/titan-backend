"""The audit log: an entry per tool call and the changes it made.

Decisions #108 (what an entry keeps), #111 (an approval request is its call's
entry) and #112 (an entry knows the thread its call came from).
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from titan_server.db import Base


class ActionClass(enum.StrEnum):
    """How much a call can change, which sets its default mode (decision #38).

    A user can change the mode of one class in one domain (decision #10); the
    policy that applies the modes comes in stage 3.
    """

    # Only looks: finding tasks, reading a note. Runs at once.
    READ = "read"
    # Changes the user's own data on the node and can be taken back: creating
    # or editing a task. Runs at once, and the reply shows an Undo.
    WRITE_INTERNAL = "write-internal"
    # Reaches outside the node and cannot be taken back: sending a message,
    # calling another service. Waits for the user's approval.
    EXTERNAL = "external"
    # Destroys data for good: emptying the trash. Waits for the user's approval.
    DESTRUCTIVE = "destructive"


class EntryStatus(enum.StrEnum):
    """Where a call stands in its life (decision #111)."""

    # Waits for the user's approval.
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    # Not decided within 24 hours; counts as rejected.
    EXPIRED = "expired"
    DONE = "done"
    FAILED = "failed"
    # The policy does not allow the call; the agent is told so.
    DENIED = "denied"


class AuditEntry(Base):
    """One tool call: what was called, for whom, and where it stands."""

    __tablename__ = "audit_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("threads.id", ondelete="SET NULL")
    )
    tool: Mapped[str]
    summary: Mapped[str]
    action_class: Mapped[ActionClass] = mapped_column(
        Enum(
            ActionClass,
            name="action_class",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda classes: [value.value for value in classes],
        ),
    )
    status: Mapped[EntryStatus] = mapped_column(
        Enum(
            EntryStatus,
            name="entry_status",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda statuses: [status.value for status in statuses],
        ),
    )
    input: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )


class AuditChange(Base):
    """What one call changed in one object (decision #108)."""

    __tablename__ = "audit_changes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    entry_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("audit_entries.id"), index=True
    )
    table_name: Mapped[str]
    object_id: Mapped[uuid.UUID]
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    version: Mapped[int]
