"""The tasks table; stage 2 keeps only what creating a task needs."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from titan_server.db import Base


class TaskStatus(enum.StrEnum):
    """Where a task stands (decision #44)."""

    OPEN = "open"
    DONE = "done"
    CANCELLED = "cancelled"


class Task(Base):
    """Something one user has to do."""

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str]
    # A string with a check rather than a PostgreSQL enum type: a status added
    # later is a new check, not an ALTER TYPE.
    status: Mapped[TaskStatus] = mapped_column(
        Enum(
            TaskStatus,
            name="task_status",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda statuses: [status.value for status in statuses],
        ),
        default=TaskStatus.OPEN,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
