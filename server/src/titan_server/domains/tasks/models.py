"""The tasks table; it keeps only what creating a task and its undo need."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from titan_server.db import Audited, Base, active_history_mapped_column


class TaskStatus(enum.StrEnum):
    """Where a task stands (decision #44)."""

    OPEN = "open"
    DONE = "done"
    CANCELLED = "cancelled"


class Task(Audited, Base):
    """Something one user has to do."""

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = active_history_mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = active_history_mapped_column()
    # A string with a check rather than a PostgreSQL enum type: a status added
    # later is a new check, not an ALTER TYPE.
    status: Mapped[TaskStatus] = active_history_mapped_column(
        Enum(
            TaskStatus,
            name="task_status",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda statuses: [status.value for status in statuses],
        ),
        default=TaskStatus.OPEN,
    )
    created_at: Mapped[datetime] = active_history_mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Set when the task goes to the trash, which every read leaves out
    # (decision #128).
    # NOTE: items in the trash are kept for good until the worker of stage 6
    # purges them after 30 days (decision #129).
    deleted_at: Mapped[datetime | None] = active_history_mapped_column(
        DateTime(timezone=True)
    )
