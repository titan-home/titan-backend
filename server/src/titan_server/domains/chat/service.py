"""Threads and their messages; every function acts for one user."""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.domains.chat.models import Message, Role, Thread, ToolCallRecord


class ThreadNotFoundError(Exception):
    """No such thread, or it belongs to another user; the two are never told apart."""


@dataclass(frozen=True)
class Usage:
    """The model of a reply and its tokens by kind (decision #35)."""

    model: str
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int


async def create_thread(session: AsyncSession, user_id: uuid.UUID) -> Thread:
    """Start an empty thread for the user."""
    thread = Thread(user_id=user_id)
    session.add(thread)
    await session.flush()
    return thread


async def get_thread(
    session: AsyncSession, user_id: uuid.UUID, thread_id: uuid.UUID
) -> Thread:
    """The user's thread with this id; raises ThreadNotFoundError otherwise."""
    thread = await session.scalar(
        select(Thread).where(Thread.id == thread_id, Thread.user_id == user_id)
    )
    if thread is None:
        raise ThreadNotFoundError
    return thread


async def add_user_message(session: AsyncSession, thread: Thread, text: str) -> Message:
    """Add what the user wrote to the thread."""
    return await _add(session, thread, Message(role=Role.USER, text=text))


async def add_reply(
    session: AsyncSession,
    thread: Thread,
    text: str,
    tool_calls: list[ToolCallRecord],
    usage: Usage,
) -> Message:
    """Add the assistant's reply with its tool calls and token usage."""
    reply = Message(
        role=Role.ASSISTANT,
        text=text,
        tool_calls=tool_calls,
        model=usage.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        cache_read_tokens=usage.cache_read_tokens,
    )
    return await _add(session, thread, reply)


async def history(session: AsyncSession, thread: Thread) -> list[Message]:
    """The thread's messages, oldest first."""
    messages = await session.scalars(
        select(Message)
        .where(Message.thread_id == thread.id)
        .order_by(Message.created_at)
    )
    return list(messages)


async def _add(session: AsyncSession, thread: Thread, message: Message) -> Message:
    message.thread_id = thread.id
    thread.last_message_at = func.clock_timestamp()
    session.add(message)
    await session.flush()
    return message
