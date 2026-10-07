"""The threads and messages tables (decision #102)."""

import enum
import uuid
from datetime import datetime
from typing import NotRequired, TypedDict

from sqlalchemy import DateTime, Enum, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from titan_server.db import Base


class Role(enum.StrEnum):
    """Who wrote a message."""

    USER = "user"
    ASSISTANT = "assistant"


class ToolCallRecord(TypedDict):
    """What a reply keeps of one tool call; the audit log keeps it all."""

    name: str
    summary: str
    ok: bool
    # The call's audit entry (decision #112); replies stored before the audit
    # log have none.
    entry_id: NotRequired[str]


class Thread(Base):
    """One conversation of one user."""

    __tablename__ = "threads"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Message(Base):
    """A user's message or the assistant's reply; a reply also keeps its usage."""

    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_thread_id_created_at", "thread_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("threads.id"))
    role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            name="message_role",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda roles: [role.value for role in roles],
        )
    )
    text: Mapped[str]
    tool_calls: Mapped[list[ToolCallRecord] | None] = mapped_column(JSONB)
    model: Mapped[str | None]
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    cache_write_tokens: Mapped[int | None]
    cache_read_tokens: Mapped[int | None]
    # clock_timestamp, not now(): now() is the start of the transaction, so a
    # message and its reply written in one transaction would tie.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
