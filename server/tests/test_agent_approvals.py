"""Tests for approving a request (autonomy spec, an approved call runs as approved)."""

import asyncio
import dataclasses
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from titan_server.agent import turn
from titan_server.agent.approvals import approve
from titan_server.agent.tool import ToolContext
from titan_server.agent.tools.tasks import CreateTaskInput, create_task
from titan_server.domains.accounts.models import User
from titan_server.domains.audit.approvals import (
    AlreadyDecidedError,
    ApprovalNotFoundError,
)
from titan_server.domains.audit.models import (
    ActionClass,
    AuditChange,
    AuditEntry,
    Domain,
    EntryStatus,
    Mode,
)
from titan_server.domains.chat.models import Message, Role
from titan_server.domains.chat.service import create_thread
from titan_server.domains.tasks import service as tasks_service
from titan_server.domains.tasks.models import Task

pytestmark = pytest.mark.anyio

# Requests made after it have not expired: nothing in these tests is that old.
LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)


def new_user(username: str = "owner") -> User:
    return User(
        id=uuid.uuid4(), username=username, password_hash="$argon2id$v=19$placeholder"
    )


def new_request(
    user_id: uuid.UUID,
    thread_id: uuid.UUID | None = None,
    tool: str = "create_task",
    title: str = "Buy milk",
) -> AuditEntry:
    """A create_task call that waits for approval, as the SDK handler leaves it."""
    return AuditEntry(
        id=uuid.uuid4(),
        user_id=user_id,
        thread_id=thread_id,
        tool=tool,
        summary=f"Creating a task: {title}",
        mode=Mode.CONFIRM,
        action_class=ActionClass.WRITE_INTERNAL,
        domain=Domain.TASKS,
        input={"title": title},
        undoable=True,
        status=EntryStatus.PENDING,
    )


async def stored(session: AsyncSession, *items: User | AuditEntry) -> None:
    session.add_all(items)
    await session.flush()


async def tasks(session: AsyncSession) -> list[str]:
    return list(await session.scalars(select(Task.title)))


async def changes(session: AsyncSession, entry: AuditEntry) -> list[AuditChange]:
    return list(
        await session.scalars(
            select(AuditChange).where(AuditChange.entry_id == entry.id)
        )
    )


async def status_of(session: AsyncSession, entry: AuditEntry) -> EntryStatus | None:
    # From the database: a rolled-back savepoint may have expired the entry,
    # and reading an expired attribute here would raise MissingGreenlet.
    status: EntryStatus | None = await session.scalar(
        select(AuditEntry.status).where(AuditEntry.id == entry.id)
    )
    return status


async def messages(session: AsyncSession) -> list[Message]:
    return list(await session.scalars(select(Message)))


async def assert_thread_told_failed(
    session: AsyncSession, entry: AuditEntry, tool: str
) -> None:
    """The entry's thread got the one message saying its call failed."""
    [message] = await messages(session)
    assert (message.thread_id, message.role, message.text, message.model) == (
        entry.thread_id,
        Role.ASSISTANT,
        "Approved: Creating a task: Buy milk — failed.",
        None,
    )
    assert message.tool_calls == [
        {
            "name": tool,
            "summary": "Creating a task: Buy milk",
            "status": "failed",
            "ok": False,
            "entry_id": str(entry.id),
            "domain": "tasks",
            "action_class": "write-internal",
        }
    ]


async def test_an_approved_call_runs_and_its_changes_are_in_the_log(
    session: AsyncSession,
) -> None:
    """An approved call runs exactly as approved 2: without asking the agent."""
    user = new_user()
    entry = new_request(user.id)
    await stored(session, user, entry)

    assert await approve(session, user.id, entry.id, LONG_AGO) is entry

    assert await status_of(session, entry) == EntryStatus.DONE
    assert await tasks(session) == ["Buy milk"]
    [change] = await changes(session, entry)
    assert change.table_name == "tasks"
    assert change.after is not None
    assert change.after["title"] == "Buy milk"


async def test_the_input_is_checked_again(session: AsyncSession) -> None:
    """Decision #120: the tool's input model checks the stored input again."""
    user = new_user()
    await stored(session, user)
    thread = await create_thread(session, user.id)
    # Stored when the model accepted it; the tool's model refuses it now.
    entry = new_request(user.id, thread.id)
    entry.input = {"title": ""}
    await stored(session, entry)

    await approve(session, user.id, entry.id, LONG_AGO)

    assert await status_of(session, entry) == EntryStatus.FAILED
    assert await tasks(session) == []
    await assert_thread_told_failed(session, entry, "create_task")


async def create_then_fail(context: ToolContext, task: CreateTaskInput) -> str:
    await tasks_service.create_task(context.session, context.user_id, task.title)
    raise RuntimeError("the database is down")


FAILING = dataclasses.replace(create_task, name="failing", run=create_then_fail)


async def test_a_failed_call_is_failed_and_keeps_no_changes(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decision #122: an approved call that fails ends failed, and says so."""
    monkeypatch.setattr(turn, "TOOLS", (*turn.TOOLS, FAILING))
    user = new_user()
    await stored(session, user)
    thread = await create_thread(session, user.id)
    entry = new_request(user.id, thread.id, tool="failing")
    await stored(session, entry)

    await approve(session, user.id, entry.id, LONG_AGO)

    assert await status_of(session, entry) == EntryStatus.FAILED
    assert await tasks(session) == []
    assert await changes(session, entry) == []
    [message] = await messages(session)
    assert message.text == "Approved: Creating a task: Buy milk — failed."
    assert message.tool_calls == [
        {
            "name": "failing",
            "summary": "Creating a task: Buy milk",
            "status": "failed",
            "ok": False,
            "entry_id": str(entry.id),
            "domain": "tasks",
            "action_class": "write-internal",
        }
    ]


async def test_an_unknown_tool_fails(session: AsyncSession) -> None:
    user = new_user()
    await stored(session, user)
    thread = await create_thread(session, user.id)
    entry = new_request(user.id, thread.id, tool="no_such_tool")
    await stored(session, entry)

    await approve(session, user.id, entry.id, LONG_AGO)

    assert await status_of(session, entry) == EntryStatus.FAILED
    assert await tasks(session) == []
    await assert_thread_told_failed(session, entry, "no_such_tool")


async def test_the_thread_gets_approved_done(session: AsyncSession) -> None:
    """An approved call runs exactly as approved 3: the result is in the thread."""
    user = new_user()
    await stored(session, user)
    thread = await create_thread(session, user.id)
    entry = new_request(user.id, thread.id)
    await stored(session, entry)

    await approve(session, user.id, entry.id, LONG_AGO)

    [message] = await messages(session)
    assert (message.thread_id, message.role, message.text, message.model) == (
        thread.id,
        Role.ASSISTANT,
        "Approved: Creating a task: Buy milk — done.",
        None,
    )
    assert message.tool_calls == [
        {
            "name": "create_task",
            "summary": "Creating a task: Buy milk",
            "status": "done",
            "ok": True,
            "entry_id": str(entry.id),
            "domain": "tasks",
            "action_class": "write-internal",
        }
    ]


async def test_a_request_without_a_thread_runs_and_writes_no_message(
    session: AsyncSession,
) -> None:
    user = new_user()
    entry = new_request(user.id)
    await stored(session, user, entry)

    await approve(session, user.id, entry.id, LONG_AGO)

    assert await tasks(session) == ["Buy milk"]
    assert await messages(session) == []


@pytest.mark.parametrize("whose", ["another user's", "missing"])
async def test_another_users_request_is_not_found(
    session: AsyncSession, whose: str
) -> None:
    """Approvals 4: only the user whose agent made the request decides it."""
    owner, other = new_user("owner"), new_user("other")
    entry = new_request(owner.id)
    await stored(session, owner, other, entry)
    entry_id = entry.id if whose == "another user's" else uuid.uuid4()

    with pytest.raises(ApprovalNotFoundError):
        await approve(session, other.id, entry_id, LONG_AGO)

    assert await status_of(session, entry) == EntryStatus.PENDING
    assert await tasks(session) == []


async def test_a_decided_request_is_not_decided_again(session: AsyncSession) -> None:
    """Approvals 3: a second Approve changes nothing (decision #121)."""
    user = new_user()
    entry = new_request(user.id)
    await stored(session, user, entry)
    await approve(session, user.id, entry.id, LONG_AGO)

    with pytest.raises(AlreadyDecidedError) as raised:
        await approve(session, user.id, entry.id, LONG_AGO)

    assert raised.value.status == EntryStatus.DONE
    assert await tasks(session) == ["Buy milk"]


@pytest.fixture
async def engine(database: URL) -> AsyncIterator[AsyncEngine]:
    """An engine whose sessions commit; what they wrote is deleted after the test."""
    engine = create_async_engine(database)
    yield engine
    async with engine.begin() as connection:
        for statement in (
            "DELETE FROM audit_changes WHERE entry_id IN"
            " (SELECT id FROM audit_entries WHERE user_id IN"
            " (SELECT id FROM users WHERE username LIKE 'race-%'))",
            "DELETE FROM audit_entries WHERE user_id IN"
            " (SELECT id FROM users WHERE username LIKE 'race-%')",
            "DELETE FROM tasks WHERE user_id IN"
            " (SELECT id FROM users WHERE username LIKE 'race-%')",
            "DELETE FROM users WHERE username LIKE 'race-%'",
        ):
            await connection.execute(text(statement))
    await engine.dispose()


async def test_an_expired_request_never_runs(session: AsyncSession) -> None:
    """Expiry 2: approving a request past its deadline runs nothing."""
    user = new_user()
    entry = new_request(user.id)
    await stored(session, user, entry)

    with pytest.raises(AlreadyDecidedError, match="expired"):
        await approve(session, user.id, entry.id, entry.created_at)

    assert await status_of(session, entry) == EntryStatus.EXPIRED
    assert await tasks(session) == []
    assert await changes(session, entry) == []


async def test_two_approvals_at_once_run_the_call_once(engine: AsyncEngine) -> None:
    """Approvals 3 and decision #121: the second waits for the lock, then is told."""
    user = new_user(f"race-{uuid.uuid4().hex[:8]}")
    entry = new_request(user.id)
    user_id, entry_id = user.id, entry.id
    async with AsyncSession(engine) as setup, setup.begin():
        await stored(setup, user, entry)

    async def decide() -> EntryStatus:
        # Each Approve in its own transaction, as two requests to the API.
        async with AsyncSession(engine) as session, session.begin():
            approved = await approve(session, user_id, entry_id, LONG_AGO)
            return approved.status

    results = await asyncio.gather(decide(), decide(), return_exceptions=True)

    assert EntryStatus.DONE in results
    [refused] = [result for result in results if isinstance(result, BaseException)]
    assert isinstance(refused, AlreadyDecidedError)
    assert refused.status == EntryStatus.DONE
    async with AsyncSession(engine) as check:
        titles = await check.scalars(select(Task.title).where(Task.user_id == user_id))
        assert list(titles) == ["Buy milk"]
