"""Tests for catching a call's changes from the session (decisions #108, #110)."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.domains.accounts.models import User
from titan_server.domains.audit.capture import (
    AUDIT_ENTRY,
    drop_call,
    finish_call,
    from_json,
    start_call,
    to_json,
)
from titan_server.domains.audit.models import (
    ActionClass,
    AuditChange,
    AuditEntry,
    Domain,
    EntryStatus,
    Mode,
)
from titan_server.domains.tasks.models import Task, TaskStatus
from titan_server.domains.tasks.service import create_task


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("id", uuid.uuid4()),
        ("title", "Buy milk"),
        ("status", TaskStatus.DONE),
        ("created_at", datetime(2026, 10, 7, 9, 30, tzinfo=UTC)),
        ("version", 3),
    ],
)
def test_a_value_comes_back_as_it_was(column: str, value: object) -> None:
    task_column = Task.__table__.c[column]

    back = from_json(task_column, to_json(task_column, value))

    assert (back, type(back)) == (value, type(value))


def test_an_empty_value_stays_empty() -> None:
    # A column that may be NULL, such as a due date, has no value to convert.
    column = Task.__table__.c.created_at

    assert (to_json(column, None), from_json(column, None)) == (None, None)


def test_a_value_is_kept_as_plain_json() -> None:
    assert to_json(Task.__table__.c.status, TaskStatus.DONE) == "done"
    assert (
        to_json(Task.__table__.c.created_at, datetime(2026, 10, 7, 9, 30, tzinfo=UTC))
        == "2026-10-07T09:30:00Z"
    )


async def new_user(session: AsyncSession) -> User:
    user = User(username="owner", password_hash="$argon2id$v=19$placeholder")
    session.add(user)
    await session.flush()
    return user


async def new_entry(session: AsyncSession, user: User) -> AuditEntry:
    entry = AuditEntry(
        user_id=user.id,
        tool="create_task",
        action_class=ActionClass.WRITE_INTERNAL,
        domain=Domain.TASKS,
        mode=Mode.AUTO_UNDO,
        input={"title": "Buy milk"},
        summary="Creating a task: Buy milk",
        status=EntryStatus.DONE,
    )
    session.add(entry)
    await session.flush()
    return entry


async def changes(session: AsyncSession, entry: AuditEntry) -> list[AuditChange]:
    await session.flush()
    return list(
        await session.scalars(
            select(AuditChange).where(AuditChange.entry_id == entry.id)
        )
    )


@pytest.mark.anyio
async def test_a_created_object_is_kept_whole(session: AsyncSession) -> None:
    user = await new_user(session)
    entry = await new_entry(session, user)

    start_call(session, entry)
    task = await create_task(session, user.id, "Buy milk")
    await finish_call(session)

    [change] = await changes(session, entry)
    assert (change.table_name, change.object_id, change.before, change.version) == (
        "tasks",
        task.id,
        None,
        1,
    )
    assert change.after is not None
    assert {key: change.after[key] for key in ("title", "status", "user_id")} == {
        "title": "Buy milk",
        "status": "open",
        "user_id": str(user.id),
    }


@pytest.mark.anyio
async def test_a_change_keeps_only_the_changed_fields(session: AsyncSession) -> None:
    user = await new_user(session)
    task = await create_task(session, user.id, "Buy milk")
    entry = await new_entry(session, user)

    start_call(session, entry)
    task.title = "Buy oat milk"
    await finish_call(session)

    [change] = await changes(session, entry)
    assert (change.object_id, change.before, change.after, change.version) == (
        task.id,
        {"title": "Buy milk"},
        {"title": "Buy oat milk"},
        2,
    )


@pytest.mark.anyio
async def test_an_object_created_and_changed_in_one_call_is_one_change(
    session: AsyncSession,
) -> None:
    # create_task flushes by itself, so the call spans two flushes.
    user = await new_user(session)
    entry = await new_entry(session, user)

    start_call(session, entry)
    task = await create_task(session, user.id, "Buy milk")
    task.title = "Buy oat milk"
    await finish_call(session)

    [change] = await changes(session, entry)
    assert change.before is None
    assert change.after is not None
    assert (change.after["title"], change.version) == ("Buy oat milk", 2)


@pytest.mark.anyio
async def test_a_deleted_object_is_kept_whole(session: AsyncSession) -> None:
    user = await new_user(session)
    task = await create_task(session, user.id, "Buy milk")
    entry = await new_entry(session, user)

    start_call(session, entry)
    await session.delete(task)
    await finish_call(session)

    [change] = await changes(session, entry)
    assert change.after is None
    assert change.before is not None
    assert change.before["title"] == "Buy milk"


@pytest.mark.anyio
async def test_changes_outside_a_call_are_not_recorded(session: AsyncSession) -> None:
    user = await new_user(session)
    entry = await new_entry(session, user)
    start_call(session, entry)
    await finish_call(session)

    task = await create_task(session, user.id, "Buy milk")
    task.title = "Buy oat milk"

    assert await changes(session, entry) == []


@pytest.mark.anyio
async def test_an_object_created_and_deleted_in_one_call_leaves_no_change(
    session: AsyncSession,
) -> None:
    user = await new_user(session)
    entry = await new_entry(session, user)

    start_call(session, entry)
    task = await create_task(session, user.id, "Buy milk")
    await session.delete(task)
    await finish_call(session)

    assert await changes(session, entry) == []


@pytest.mark.anyio
async def test_an_object_changed_then_deleted_keeps_its_row_from_before_the_call(
    session: AsyncSession,
) -> None:
    user = await new_user(session)
    task = await create_task(session, user.id, "Buy milk")
    entry = await new_entry(session, user)

    start_call(session, entry)
    task.title = "Buy oat milk"
    await session.flush()
    await session.delete(task)
    await finish_call(session)

    [change] = await changes(session, entry)
    assert change.after is None
    assert change.before is not None
    assert (change.before["title"], change.before["status"]) == ("Buy milk", "open")


@pytest.mark.anyio
async def test_a_dropped_call_records_none_of_its_changes(
    session: AsyncSession,
) -> None:
    # Its changes were rolled back (decision #122), so there is nothing to log.
    user = await new_user(session)
    entry = await new_entry(session, user)

    start_call(session, entry)
    await create_task(session, user.id, "Buy milk")
    drop_call(session)
    await create_task(session, user.id, "Buy oat milk")

    # The call has ended: later flushes are not its, and nothing is logged.
    assert AUDIT_ENTRY not in session.info
    assert await changes(session, entry) == []
