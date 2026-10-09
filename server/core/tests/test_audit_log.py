"""Tests for the audit log tables (decisions #108, #111, #112)."""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from titan_core.domains.accounts.models import User
from titan_core.domains.audit.models import (
    ActionClass,
    AuditChange,
    AuditEntry,
    Domain,
    EntryStatus,
    Mode,
)
from titan_core.domains.chat import service as chat

pytestmark = pytest.mark.anyio


async def new_user(session: AsyncSession) -> User:
    user = User(username="owner", password_hash="$argon2id$v=19$placeholder")
    session.add(user)
    await session.flush()
    return user


def create_task_entry(user: User, thread_id: uuid.UUID | None) -> AuditEntry:
    return AuditEntry(
        user_id=user.id,
        thread_id=thread_id,
        tool="create_task",
        action_class=ActionClass.WRITE_INTERNAL,
        domain=Domain.TASKS,
        mode=Mode.AUTO_UNDO,
        input={"title": "Buy milk"},
        undoable=True,
        summary="Creating a task: Buy milk",
        status=EntryStatus.DONE,
    )


async def test_an_entry_keeps_the_call_and_its_thread(session: AsyncSession) -> None:
    """Audit log 1: when, which tool, its class, the input, the outcome."""
    user = await new_user(session)
    thread = await chat.create_thread(session, user.id)
    entry = create_task_entry(user, thread.id)
    session.add(entry)
    await session.flush()
    await session.refresh(entry)

    assert isinstance(entry.id, uuid.UUID)
    assert (
        entry.user_id,
        entry.thread_id,
        entry.tool,
        entry.action_class,
        entry.input,
        entry.summary,
        entry.status,
    ) == (
        user.id,
        thread.id,
        "create_task",
        ActionClass.WRITE_INTERNAL,
        {"title": "Buy milk"},
        "Creating a task: Buy milk",
        EntryStatus.DONE,
    )
    assert entry.created_at.tzinfo is not None


async def test_an_entry_from_outside_a_chat_has_no_thread(
    session: AsyncSession,
) -> None:
    user = await new_user(session)
    entry = create_task_entry(user, None)
    session.add(entry)
    await session.flush()

    assert entry.thread_id is None


async def test_an_entry_outlives_its_thread(session: AsyncSession) -> None:
    # Entries are kept for good (decision #41); deleting a thread for good
    # erases only the link to it.
    user = await new_user(session)
    thread = await chat.create_thread(session, user.id)
    entry = create_task_entry(user, thread.id)
    session.add(entry)
    await session.flush()

    await session.execute(text("DELETE FROM threads WHERE id = :id"), {"id": thread.id})
    await session.refresh(entry)

    assert entry.thread_id is None


async def test_the_status_is_one_of_the_decided_ones(session: AsyncSession) -> None:
    user = await new_user(session)
    entry = create_task_entry(user, None)
    session.add(entry)
    await session.flush()

    with pytest.raises(IntegrityError):
        await session.execute(
            text("UPDATE audit_entries SET status = 'later' WHERE id = :id"),
            {"id": entry.id},
        )


async def test_an_entry_keeps_one_change_per_object(session: AsyncSession) -> None:
    """Decision #108: the changed fields before and after; a whole created row."""
    user = await new_user(session)
    entry = create_task_entry(user, None)
    session.add(entry)
    await session.flush()
    created, changed = uuid.uuid4(), uuid.uuid4()
    session.add_all(
        [
            AuditChange(
                entry_id=entry.id,
                table_name="tasks",
                object_id=created,
                before=None,
                after={"title": "Buy milk", "status": "open"},
                version=1,
            ),
            AuditChange(
                entry_id=entry.id,
                table_name="tasks",
                object_id=changed,
                before={"title": "Buy bread"},
                after={"title": "Buy rye bread"},
                version=4,
            ),
        ]
    )
    await session.flush()

    rows = (
        await session.scalars(
            select(AuditChange)
            .where(AuditChange.entry_id == entry.id)
            .order_by(AuditChange.version)
        )
    ).all()

    assert [
        (row.table_name, row.object_id, row.before, row.after, row.version)
        for row in rows
    ] == [
        ("tasks", created, None, {"title": "Buy milk", "status": "open"}, 1),
        ("tasks", changed, {"title": "Buy bread"}, {"title": "Buy rye bread"}, 4),
    ]


async def test_a_change_belongs_to_an_existing_entry(session: AsyncSession) -> None:
    session.add(
        AuditChange(
            entry_id=uuid.uuid4(),
            table_name="tasks",
            object_id=uuid.uuid4(),
            before=None,
            after={"title": "Buy milk"},
            version=1,
        )
    )

    with pytest.raises(IntegrityError):
        await session.flush()
