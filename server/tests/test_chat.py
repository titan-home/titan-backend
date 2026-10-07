"""Tests for threads and messages (shared/.../domains/chat.md, decision #102)."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.domains.accounts.models import User
from titan_server.domains.chat.models import Role, Thread, ToolCallRecord
from titan_server.domains.chat.service import (
    ThreadNotFoundError,
    Usage,
    add_reply,
    add_user_message,
    create_thread,
    get_thread,
    history,
)

pytestmark = pytest.mark.anyio

USAGE = Usage(
    model="claude-opus-5-5",
    input_tokens=1200,
    output_tokens=40,
    cache_write_tokens=900,
    cache_read_tokens=0,
)
CREATED: list[ToolCallRecord] = [
    {"name": "create_task", "summary": "Creating a task: buy milk", "ok": True}
]


async def new_user(session: AsyncSession, username: str = "owner") -> User:
    user = User(username=username, password_hash="$argon2id$v=19$placeholder")
    session.add(user)
    await session.flush()
    return user


async def test_a_user_gets_their_own_thread(session: AsyncSession) -> None:
    user = await new_user(session)
    thread = await create_thread(session, user.id)

    assert await get_thread(session, user.id, thread.id) is thread
    assert isinstance(thread.id, uuid.UUID)
    assert thread.title is None


@pytest.mark.parametrize("whose", ["another user's", "missing"])
async def test_another_users_thread_is_not_found(
    session: AsyncSession, whose: str
) -> None:
    """Threads 1: another user's thread answers 404, like one that does not exist."""
    owner = await new_user(session, "owner")
    other = await new_user(session, "other")
    thread = await create_thread(session, owner.id)
    thread_id = thread.id if whose == "another user's" else uuid.uuid4()

    with pytest.raises(ThreadNotFoundError):
        await get_thread(session, other.id, thread_id)


async def test_history_is_oldest_first_within_one_transaction(
    session: AsyncSession,
) -> None:
    user = await new_user(session)
    thread = await create_thread(session, user.id)

    await add_user_message(session, thread, "add a task to buy milk")
    await add_reply(session, thread, "Added.", CREATED, USAGE)
    await add_user_message(session, thread, "thanks")

    messages = await history(session, thread)
    assert [(m.role, m.text) for m in messages] == [
        (Role.USER, "add a task to buy milk"),
        (Role.ASSISTANT, "Added."),
        (Role.USER, "thanks"),
    ]


async def test_a_reply_keeps_its_tool_calls_and_tokens(session: AsyncSession) -> None:
    """Token usage 1: the model and its four kinds of tokens."""
    user = await new_user(session)
    thread = await create_thread(session, user.id)

    reply = await add_reply(session, thread, "Added.", CREATED, USAGE)
    await session.refresh(reply)

    assert reply.tool_calls == CREATED
    assert (
        reply.model,
        reply.input_tokens,
        reply.output_tokens,
        reply.cache_write_tokens,
        reply.cache_read_tokens,
    ) == ("claude-opus-5-5", 1200, 40, 900, 0)


async def test_a_message_the_node_writes_has_no_model_or_tokens(
    session: AsyncSession,
) -> None:
    """Decision #120: Claude was not asked, so there is no usage to keep."""
    user = await new_user(session)
    thread = await create_thread(session, user.id)

    reply = await add_reply(session, thread, "Approved.", CREATED, None)
    await session.refresh(reply)

    assert (reply.role, reply.tool_calls) == (Role.ASSISTANT, CREATED)
    assert (
        reply.model,
        reply.input_tokens,
        reply.output_tokens,
        reply.cache_write_tokens,
        reply.cache_read_tokens,
    ) == (None, None, None, None, None)


async def test_a_new_message_moves_the_thread_up(session: AsyncSession) -> None:
    """Threads 2: the list is ordered by the last message."""
    user = await new_user(session)
    thread = await create_thread(session, user.id)
    await session.refresh(thread)
    started = thread.last_message_at

    await add_user_message(session, thread, "hello")
    await session.refresh(thread)

    assert thread.last_message_at > started


async def test_the_role_is_user_or_assistant(session: AsyncSession) -> None:
    user = await new_user(session)
    thread = await create_thread(session, user.id)
    message = await add_user_message(session, thread, "hello")

    with pytest.raises(IntegrityError):
        await session.execute(
            text("UPDATE messages SET role = 'system' WHERE id = :id"),
            {"id": message.id},
        )


async def test_a_thread_belongs_to_an_existing_user(session: AsyncSession) -> None:
    session.add(Thread(user_id=uuid.uuid4()))

    with pytest.raises(IntegrityError):
        await session.flush()
