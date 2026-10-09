"""Tests for the list of the audit log (autonomy spec, audit log; decision #136)."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from titan_core.domains.accounts.models import User
from titan_core.domains.audit.log import list_entries
from titan_core.domains.audit.models import (
    ActionClass,
    AuditEntry,
    Domain,
    EntryStatus,
    Mode,
)

pytestmark = pytest.mark.anyio


async def new_user(session: AsyncSession, username: str = "owner") -> User:
    user = User(username=username, password_hash="$argon2id$v=19$placeholder")
    session.add(user)
    await session.flush()
    return user


async def new_entry(
    session: AsyncSession,
    user: User,
    status: EntryStatus = EntryStatus.DONE,
    undoes: AuditEntry | None = None,
    created_at: datetime | None = None,
    entry_id: uuid.UUID | None = None,
) -> AuditEntry:
    """A call in the log; an undo when it takes back another entry."""
    entry = AuditEntry(
        id=entry_id or uuid.uuid4(),
        user_id=user.id,
        tool="undo" if undoes else "create_task",
        summary="Creating a task: Buy milk",
        mode=None if undoes else Mode.AUTO_UNDO,
        action_class=ActionClass.WRITE_INTERNAL,
        domain=Domain.TASKS,
        input={},
        undoable=True,
        undoes_entry_id=undoes.id if undoes else None,
        status=status,
    )
    if created_at is not None:
        entry.created_at = created_at
    session.add(entry)
    # One flush per entry: each gets its own created_at, in order.
    await session.flush()
    return entry


async def pages(
    session: AsyncSession, user: User, limit: int
) -> list[list[AuditEntry]]:
    """Every page of the user's log, following the cursor."""
    result = []
    after = None
    while True:
        page, after = await list_entries(session, user.id, limit, after)
        result.append(page)
        if after is None:
            return result


async def test_the_log_lists_every_status_newest_first_undos_included(
    session: AsyncSession,
) -> None:
    """Calls that did not run are listed too (autonomy spec, audit log 2)."""
    user = await new_user(session)
    done = await new_entry(session, user)
    undo = await new_entry(session, user, undoes=done)
    rejected = await new_entry(session, user, EntryStatus.REJECTED)
    pending = await new_entry(session, user, EntryStatus.PENDING)

    assert await list_entries(session, user.id, 10, None) == (
        [pending, rejected, undo, done],
        None,
    )


async def test_the_log_is_paged_newest_first(session: AsyncSession) -> None:
    """Decision #124: a cursor pages through each entry once."""
    user = await new_user(session)
    first, second, third = [await new_entry(session, user) for _ in range(3)]

    assert await pages(session, user, 2) == [[third, second], [first]]


async def test_entries_with_the_same_time_are_neither_skipped_nor_repeated(
    session: AsyncSession,
) -> None:
    user = await new_user(session)
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    low, middle, high = [
        await new_entry(session, user, created_at=moment, entry_id=uuid.UUID(int=n))
        for n in (1, 2, 3)
    ]

    assert await pages(session, user, 1) == [[high], [middle], [low]]


async def test_a_full_last_page_has_no_next(session: AsyncSession) -> None:
    user = await new_user(session)
    only = await new_entry(session, user)

    assert await list_entries(session, user.id, 1, None) == ([only], None)


async def test_no_entries_is_one_empty_page(session: AsyncSession) -> None:
    user = await new_user(session)

    assert await list_entries(session, user.id, 2, None) == ([], None)


async def test_another_users_entries_are_never_listed(session: AsyncSession) -> None:
    """Audit log 3: a user sees only their own log."""
    user = await new_user(session, "owner")
    other = await new_user(session, "other")
    mine = await new_entry(session, user)
    await new_entry(session, other)

    assert await pages(session, user, 2) == [[mine]]


@pytest.mark.parametrize("cursor", ["", "not base64!", "bm90IGEgY3Vyc29y"])
async def test_a_malformed_cursor_is_a_value_error(
    session: AsyncSession, cursor: str
) -> None:
    user = await new_user(session)

    with pytest.raises(ValueError):
        await list_entries(session, user.id, 2, cursor)


@pytest.mark.parametrize("limit", [0, -1])
async def test_a_limit_below_one_is_a_value_error(
    session: AsyncSession, limit: int
) -> None:
    user = await new_user(session)

    with pytest.raises(ValueError):
        await list_entries(session, user.id, limit, None)
