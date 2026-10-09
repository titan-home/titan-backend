"""The audit log: an entry per tool call and the changes it made.

Decisions #108 (what an entry keeps), #111 (an approval request is its call's
entry) and #112 (an entry knows the thread its call came from).
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from titan_server.db import Base
from titan_server.domains.chat.models import ToolCallRecord


class ActionClass(enum.StrEnum):
    """How much a call can change, which sets its default mode (decision #38).

    A user can change the mode of one class in one domain (decision #10).
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


class Domain(enum.StrEnum):
    """The area of the user's data a tool works in (decision #114).

    A user's mode for a class can differ per domain (decision #10). A value is
    added with the first tool of its domain.
    """

    TASKS = "tasks"


class Mode(enum.StrEnum):
    """What happens when the agent calls a tool (autonomy spec, modes)."""

    # Runs; shows only in the audit log.
    AUTO = "auto"
    # Runs at once; the reply shows it with an Undo (decision #37).
    AUTO_UNDO = "auto-undo"
    # Does not run; waits for the user's approval.
    CONFIRM = "confirm"
    # Does not run; the agent is told it is not allowed.
    DENY = "deny"


class EntryStatus(enum.StrEnum):
    """Where a call stands in its life (decision #111)."""

    # Waits for the user's approval.
    PENDING = "pending"
    REJECTED = "rejected"
    # Not decided within 24 hours; counts as rejected.
    EXPIRED = "expired"
    # Ran, at once or once approved (decision #123); its mode tells which.
    DONE = "done"
    FAILED = "failed"
    # The policy does not allow the call; the agent is told so.
    DENIED = "denied"


class AuditEntry(Base):
    """One tool call: what was called, for whom, and where it stands."""

    __tablename__ = "audit_entries"
    __table_args__ = (
        # A user's pending requests, in the order they are paged (decision #124).
        Index(
            "ix_audit_entries_pending",
            "user_id",
            "created_at",
            "id",
            postgresql_where=text("status = 'pending'"),
        ),
        # The list of the log, newest first (decision #136).
        Index("ix_audit_entries_user_created", "user_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("threads.id", ondelete="SET NULL")
    )
    tool: Mapped[str]
    summary: Mapped[str]
    # Empty for an undo: the user's own act, which the policy does not decide
    # (decision #131).
    mode: Mapped[Mode | None] = mapped_column(
        Enum(
            Mode,
            name="mode",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda modes: [mode.value for mode in modes],
        )
    )
    action_class: Mapped[ActionClass] = mapped_column(
        Enum(
            ActionClass,
            name="action_class",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda classes: [value.value for value in classes],
        ),
    )
    # The tool's domain (decision #114), for the detailed view of tool activity
    # (decision #119).
    domain: Mapped[Domain] = mapped_column(
        Enum(
            Domain,
            name="domain",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda domains: [domain.value for domain in domains],
        )
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
    # The tool's undoable when it was called, so a tool changed or removed
    # later does not change the undo of past calls (decision #130).
    undoable: Mapped[bool]
    # The entry this undo took back; unique, so an entry is undone once
    # (decision #131).
    undoes_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("audit_entries.id"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )


def call_record(entry: AuditEntry) -> ToolCallRecord:
    """What a reply keeps of entry's call, as it stands now (decision #119)."""
    return {
        "name": entry.tool,
        "summary": entry.summary,
        "status": entry.status.value,
        "ok": entry.status == EntryStatus.DONE,
        "entry_id": str(entry.id),
        "domain": entry.domain.value,
        "action_class": entry.action_class.value,
        "mode": None if entry.mode is None else entry.mode.value,
    }


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
