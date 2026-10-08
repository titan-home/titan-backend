"""Tests for undoing an action (autonomy spec, undo from the audit log)."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.domains.accounts.models import User
from titan_server.domains.audit.capture import finish_call, start_call
from titan_server.domains.audit.models import (
    ActionClass,
    AuditChange,
    AuditEntry,
    Domain,
    EntryStatus,
    Mode,
    call_record,
)
from titan_server.domains.audit.undo import (
    ALREADY_UNDONE,
    CHANGED_LATER,
    NEVER_RAN,
    NOT_UNDOABLE,
    TOO_OLD,
    UNDO_WINDOW,
    EntryNotFoundError,
    UndoRefusedError,
    undo,
)
from titan_server.domains.chat.models import Message
from titan_server.domains.chat.service import create_thread
from titan_server.domains.tasks import service as tasks
from titan_server.domains.tasks.models import Task

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


async def new_user(session: AsyncSession, username: str = "owner") -> User:
    user = User(username=username, password_hash="$argon2id$v=19$placeholder")
    session.add(user)
    await session.flush()
    return user


async def called(
    session: AsyncSession,
    user: User,
    run: Callable[[], Awaitable[object]],
    thread_id: uuid.UUID | None = None,
    summary: str = "Creating a task: Buy milk",
    status: EntryStatus = EntryStatus.DONE,
) -> AuditEntry:
    """An entry whose call ran run, its changes caught as the tool wrapper does."""
    entry = AuditEntry(
        user_id=user.id,
        thread_id=thread_id,
        tool="create_task",
        summary=summary,
        mode=Mode.AUTO_UNDO,
        action_class=ActionClass.WRITE_INTERNAL,
        domain=Domain.TASKS,
        input={},
        undoable=True,
        status=status,
    )
    session.add(entry)
    await session.flush()
    start_call(session, entry)
    await run()
    await finish_call(session)
    await session.flush()
    return entry


async def created(
    session: AsyncSession, user: User, thread_id: uuid.UUID | None = None
) -> tuple[AuditEntry, Task]:
    """A call of create_task that created Buy milk."""
    made: list[Task] = []

    async def run() -> None:
        made.append(await tasks.create_task(session, user.id, "Buy milk"))

    entry = await called(session, user, run, thread_id)
    return entry, made[0]


async def changed_later(session: AsyncSession, task: Task) -> None:
    """The task edited after the action, outside any call: its version goes up."""
    task.title = "Buy oat milk"
    await session.flush()


async def undos(session: AsyncSession) -> list[AuditEntry]:
    return list(
        await session.scalars(select(AuditEntry).where(AuditEntry.tool == "undo"))
    )


async def refused(
    session: AsyncSession, user: User, entry: AuditEntry, reason: str
) -> None:
    """The undo is refused with reason, and nothing is written."""
    with pytest.raises(UndoRefusedError) as raised:
        await undo(session, user.id, entry.id, NOW)
    assert str(raised.value) == reason
    assert await undos(session) == []


async def test_undoing_a_created_task_moves_it_to_the_trash(
    session: AsyncSession,
) -> None:
    """Undo 4: a created item moves to the trash (decision #109)."""
    user = await new_user(session)
    thread = await create_thread(session, user.id)
    entry, task = await created(session, user, thread.id)

    undone = await undo(session, user.id, entry.id, NOW)

    await session.refresh(task)
    assert task.deleted_at == NOW
    # Its own entry, outside the policy (decision #131).
    assert (
        undone.tool,
        undone.summary,
        undone.mode,
        undone.action_class,
        undone.domain,
        undone.thread_id,
        undone.status,
        undone.undoable,
        undone.undoes_entry_id,
    ) == (
        "undo",
        "Undo: Creating a task: Buy milk",
        None,
        ActionClass.WRITE_INTERNAL,
        Domain.TASKS,
        thread.id,
        EntryStatus.DONE,
        True,
        entry.id,
    )
    # The undone entry is not changed (decision #111).
    assert entry.status == EntryStatus.DONE


async def test_an_undo_is_written_to_the_log(session: AsyncSession) -> None:
    """Undo 3: its changes are caught like any call's (decision #110)."""
    user = await new_user(session)
    entry, task = await created(session, user)

    undone = await undo(session, user.id, entry.id, NOW)

    [change] = await session.scalars(
        select(AuditChange).where(AuditChange.entry_id == undone.id)
    )
    assert (change.table_name, change.object_id) == ("tasks", task.id)
    assert (change.before, change.after) == (
        {"deleted_at": None},
        {"deleted_at": "2026-10-08T12:00:00Z"},
    )
    assert change.version == 2


async def test_undoing_a_change_puts_the_old_values_back(
    session: AsyncSession,
) -> None:
    """Undo 4: old values return."""
    user = await new_user(session)
    task = await tasks.create_task(session, user.id, "Buy milk")

    async def rename() -> None:
        task.title = "Buy oat milk"

    entry = await called(session, user, rename, summary="Renaming a task")

    await undo(session, user.id, entry.id, NOW)

    await session.refresh(task)
    assert (task.title, task.deleted_at) == ("Buy milk", None)


async def test_the_thread_is_told(session: AsyncSession) -> None:
    """Undo 6 (decision #133): a message the node writes, without usage."""
    user = await new_user(session)
    thread = await create_thread(session, user.id)
    entry, _ = await created(session, user, thread.id)

    undone = await undo(session, user.id, entry.id, NOW)

    [message] = await session.scalars(select(Message))
    assert (message.thread_id, message.text, message.model) == (
        thread.id,
        "Undone: Creating a task: Buy milk.",
        None,
    )
    assert message.tool_calls == [call_record(undone)]


async def test_an_action_outside_a_chat_tells_no_thread(
    session: AsyncSession,
) -> None:
    user = await new_user(session)
    entry, _ = await created(session, user)

    await undo(session, user.id, entry.id, NOW)

    assert list(await session.scalars(select(Message))) == []


async def test_an_undo_can_be_undone(session: AsyncSession) -> None:
    """Undo 7 (decision #132): undoing the undo puts the action back."""
    user = await new_user(session)
    entry, task = await created(session, user)
    first = await undo(session, user.id, entry.id, NOW)

    second = await undo(session, user.id, first.id, NOW)

    await session.refresh(task)
    assert task.deleted_at is None
    assert second.undoes_entry_id == first.id
    assert second.summary == "Undo: Undo: Creating a task: Buy milk"


async def test_a_task_changed_later_is_not_undone(session: AsyncSession) -> None:
    """Undo 2 (decision #134): never overwrites a later change."""
    user = await new_user(session)
    entry, task = await created(session, user)
    await changed_later(session, task)

    await refused(session, user, entry, CHANGED_LATER)

    await session.refresh(task)
    assert (task.title, task.deleted_at) == ("Buy oat milk", None)


async def two_tasks(session: AsyncSession, user: User) -> tuple[AuditEntry, list[Task]]:
    """One call that created two tasks."""
    made: list[Task] = []

    async def run() -> None:
        for title in ("Buy milk", "Buy bread"):
            made.append(await tasks.create_task(session, user.id, title))

    entry = await called(session, user, run, summary="Creating two tasks")
    return entry, made


async def test_an_action_on_several_items_is_undone_whole(
    session: AsyncSession,
) -> None:
    """Undo 5."""
    user = await new_user(session)
    entry, made = await two_tasks(session, user)

    await undo(session, user.id, entry.id, NOW)

    for task in made:
        await session.refresh(task)
    assert [task.deleted_at for task in made] == [NOW, NOW]


async def test_one_item_changed_later_refuses_the_whole_undo(
    session: AsyncSession,
) -> None:
    """Undo 5: if any of them changed after the action, nothing is undone."""
    user = await new_user(session)
    entry, made = await two_tasks(session, user)
    await changed_later(session, made[1])

    await refused(session, user, entry, CHANGED_LATER)

    for task in made:
        await session.refresh(task)
    assert [task.deleted_at for task in made] == [None, None]


async def test_an_action_is_undone_once(session: AsyncSession) -> None:
    """Decision #131: a second undo of one entry is refused."""
    user = await new_user(session)
    entry, _ = await created(session, user)
    await undo(session, user.id, entry.id, NOW)

    with pytest.raises(UndoRefusedError) as raised:
        await undo(session, user.id, entry.id, NOW)

    assert str(raised.value) == ALREADY_UNDONE
    assert len(await undos(session)) == 1


async def test_an_action_older_than_a_year_is_not_undone(
    session: AsyncSession,
) -> None:
    """Undo 1 (decision #137): only while the entry is in the main log."""
    user = await new_user(session)
    entry, task = await created(session, user)
    entry.created_at = NOW - UNDO_WINDOW - timedelta(minutes=1)
    await session.flush()

    await refused(session, user, entry, TOO_OLD)

    await session.refresh(task)
    assert task.deleted_at is None


async def test_an_action_just_under_a_year_old_is_undone(
    session: AsyncSession,
) -> None:
    """Undo 1: one year, not a day less."""
    user = await new_user(session)
    entry, task = await created(session, user)
    entry.created_at = NOW - UNDO_WINDOW + timedelta(minutes=1)
    await session.flush()

    await undo(session, user.id, entry.id, NOW)

    await session.refresh(task)
    assert task.deleted_at == NOW


async def test_a_tool_that_could_not_be_undone_is_not_undone(
    session: AsyncSession,
) -> None:
    """Decision #130: the entry keeps undoable as the tool declared it."""
    user = await new_user(session)
    entry, task = await created(session, user)
    entry.undoable = False
    await session.flush()

    await refused(session, user, entry, NOT_UNDOABLE)

    await session.refresh(task)
    assert task.deleted_at is None


@pytest.mark.parametrize(
    "status",
    [
        EntryStatus.PENDING,
        EntryStatus.REJECTED,
        EntryStatus.EXPIRED,
        EntryStatus.FAILED,
        EntryStatus.DENIED,
    ],
)
async def test_a_call_that_never_ran_is_not_undone(
    session: AsyncSession, status: EntryStatus
) -> None:
    """Decision #135: only a done call has something to undo."""
    user = await new_user(session)

    async def nothing() -> None:
        pass

    entry = await called(session, user, nothing, status=status)

    await refused(session, user, entry, NEVER_RAN)


@pytest.mark.parametrize("whose", ["another user's", "missing"])
async def test_another_users_entry_is_not_found(
    session: AsyncSession, whose: str
) -> None:
    """Audit log 3: a user sees, and undoes, only their own log."""
    owner = await new_user(session, "owner")
    other = await new_user(session, "other")
    entry, task = await created(session, owner)
    entry_id = entry.id if whose == "another user's" else uuid.uuid4()

    with pytest.raises(EntryNotFoundError):
        await undo(session, other.id, entry_id, NOW)

    await session.refresh(task)
    assert task.deleted_at is None
