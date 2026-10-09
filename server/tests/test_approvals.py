"""Tests for deciding approval requests (autonomy spec, approvals)."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.domains.accounts.models import User
from titan_server.domains.audit.approvals import (
    AlreadyDecidedError,
    ApprovalNotFoundError,
    expire_overdue,
    list_pending,
    lock_pending,
    reject,
)
from titan_server.domains.audit.models import (
    ActionClass,
    AuditEntry,
    Domain,
    EntryStatus,
    Mode,
)
from titan_server.domains.chat.models import Message, Role
from titan_server.domains.chat.service import create_thread

pytestmark = pytest.mark.anyio

# Requests made after it have not expired: nothing in these tests is that old.
LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)


async def new_user(session: AsyncSession, username: str = "owner") -> User:
    user = User(username=username, password_hash="$argon2id$v=19$placeholder")
    session.add(user)
    await session.flush()
    return user


async def new_request(
    session: AsyncSession,
    user: User,
    thread_id: uuid.UUID | None = None,
    title: str = "Buy milk",
    status: EntryStatus = EntryStatus.PENDING,
) -> AuditEntry:
    """A call that waits for approval, as the SDK handler leaves it."""
    entry = AuditEntry(
        id=uuid.uuid4(),
        user_id=user.id,
        thread_id=thread_id,
        tool="create_task",
        summary=f"Creating a task: {title}",
        mode=Mode.CONFIRM,
        action_class=ActionClass.WRITE_INTERNAL,
        domain=Domain.TASKS,
        input={"title": title},
        undoable=True,
        status=status,
    )
    session.add(entry)
    # One flush per request: each gets its own created_at, in order.
    await session.flush()
    return entry


async def messages(session: AsyncSession) -> list[Message]:
    return list(await session.scalars(select(Message)))


@pytest.mark.parametrize("whose", ["another user's", "missing"])
async def test_another_users_request_is_not_found(
    session: AsyncSession, whose: str
) -> None:
    """Approvals 4: only the user whose agent made the request decides it."""
    owner = await new_user(session, "owner")
    other = await new_user(session, "other")
    entry = await new_request(session, owner)
    entry_id = entry.id if whose == "another user's" else uuid.uuid4()

    with pytest.raises(ApprovalNotFoundError):
        await lock_pending(session, other.id, entry_id, LONG_AGO)
    with pytest.raises(ApprovalNotFoundError):
        await reject(session, other.id, entry_id, LONG_AGO)
    assert entry.status == EntryStatus.PENDING


@pytest.mark.parametrize(
    "status", [EntryStatus.REJECTED, EntryStatus.DONE, EntryStatus.FAILED]
)
async def test_a_decided_request_is_not_decided_again(
    session: AsyncSession, status: EntryStatus
) -> None:
    """Approvals 3: a request is decided once (decision #121)."""
    user = await new_user(session)
    entry = await new_request(session, user, status=status)

    with pytest.raises(AlreadyDecidedError) as raised:
        await reject(session, user.id, entry.id, LONG_AGO)

    assert raised.value.status == status
    assert entry.status == status
    assert await messages(session) == []


async def test_lock_pending_returns_the_users_pending_request(
    session: AsyncSession,
) -> None:
    user = await new_user(session)
    entry = await new_request(session, user)

    assert await lock_pending(session, user.id, entry.id, LONG_AGO) is entry


async def test_reject_sets_the_status_and_tells_the_thread(
    session: AsyncSession,
) -> None:
    """Decision #120: the thread gets a message the node writes, without usage."""
    user = await new_user(session)
    thread = await create_thread(session, user.id)
    entry = await new_request(session, user, thread.id)

    assert await reject(session, user.id, entry.id, LONG_AGO) is entry

    assert entry.status == EntryStatus.REJECTED
    [message] = await messages(session)
    assert (message.thread_id, message.role, message.text, message.model) == (
        thread.id,
        Role.ASSISTANT,
        "Rejected: Creating a task: Buy milk.",
        None,
    )
    assert message.tool_calls == [
        {
            "name": "create_task",
            "summary": "Creating a task: Buy milk",
            "status": "rejected",
            "ok": False,
            "entry_id": str(entry.id),
            "domain": "tasks",
            "action_class": "write-internal",
            "mode": "confirm",
        }
    ]


async def test_reject_of_a_request_without_a_thread_adds_no_message(
    session: AsyncSession,
) -> None:
    user = await new_user(session)
    entry = await new_request(session, user)

    await reject(session, user.id, entry.id, LONG_AGO)

    assert entry.status == EntryStatus.REJECTED
    assert await messages(session) == []


async def pages(
    session: AsyncSession, user: User, limit: int
) -> list[list[AuditEntry]]:
    """Every page of the user's pending requests, following the cursor."""
    result = []
    after = None
    while True:
        page, after = await list_pending(session, user.id, limit, after, LONG_AGO)
        result.append(page)
        if after is None:
            return result


async def test_pending_requests_are_paged_oldest_first(
    session: AsyncSession,
) -> None:
    """Decision #124: a cursor pages through each request once."""
    user = await new_user(session)
    first, second, third = [
        await new_request(session, user, title=title)
        for title in ("Buy milk", "Buy bread", "Buy eggs")
    ]

    assert await pages(session, user, 2) == [[first, second], [third]]


async def test_a_full_last_page_has_no_next(session: AsyncSession) -> None:
    user = await new_user(session)
    first = await new_request(session, user)

    assert await list_pending(session, user.id, 1, None, LONG_AGO) == ([first], None)


async def test_only_the_users_pending_requests_are_listed(
    session: AsyncSession,
) -> None:
    """Approvals 4: only the user whose agent made the request sees it."""
    user = await new_user(session, "owner")
    other = await new_user(session, "other")
    pending = await new_request(session, user)
    await new_request(session, user, status=EntryStatus.DONE)
    await new_request(session, user, status=EntryStatus.REJECTED)
    await new_request(session, other)

    assert await pages(session, user, 2) == [[pending]]


async def test_a_request_decided_between_pages_does_not_skip_another(
    session: AsyncSession,
) -> None:
    """Decision #124: unlike an offset, the cursor keeps its place."""
    user = await new_user(session)
    first, second, third = [
        await new_request(session, user, title=title)
        for title in ("Buy milk", "Buy bread", "Buy eggs")
    ]

    page, after = await list_pending(session, user.id, 2, None, LONG_AGO)
    assert page == [first, second]
    await reject(session, user.id, first.id, LONG_AGO)

    assert await list_pending(session, user.id, 2, after, LONG_AGO) == ([third], None)


async def test_no_pending_requests_is_one_empty_page(session: AsyncSession) -> None:
    user = await new_user(session)

    assert await list_pending(session, user.id, 2, None, LONG_AGO) == ([], None)


@pytest.mark.parametrize("cursor", ["", "not base64!", "bm90IGEgY3Vyc29y"])
async def test_a_malformed_cursor_is_a_value_error(
    session: AsyncSession, cursor: str
) -> None:
    user = await new_user(session)

    with pytest.raises(ValueError):
        await list_pending(session, user.id, 2, cursor, LONG_AGO)


@pytest.mark.parametrize("limit", [0, -1])
async def test_a_limit_below_one_is_a_value_error(
    session: AsyncSession, limit: int
) -> None:
    user = await new_user(session)
    await new_request(session, user)

    with pytest.raises(ValueError):
        await list_pending(session, user.id, limit, None, LONG_AGO)


async def test_a_request_past_its_deadline_is_left_out_but_not_marked(
    session: AsyncSession,
) -> None:
    """Expiry 1 (decision #125): listing only hides it."""
    user = await new_user(session)
    old = await new_request(session, user, title="Buy milk")
    fresh = await new_request(session, user, title="Buy bread")

    assert await list_pending(session, user.id, 2, None, old.created_at) == (
        [fresh],
        None,
    )
    assert old.status == EntryStatus.PENDING


@pytest.mark.parametrize("decide", [lock_pending, reject])
async def test_deciding_a_request_past_its_deadline_expires_it(
    session: AsyncSession, decide: Callable[..., Awaitable[AuditEntry]]
) -> None:
    """Expiry 2 to 4: marked, its thread told, and the decision refused."""
    user = await new_user(session)
    thread = await create_thread(session, user.id)
    entry = await new_request(session, user, thread.id)

    # A deadline at the request's creation time is already past.
    with pytest.raises(AlreadyDecidedError) as raised:
        await decide(session, user.id, entry.id, entry.created_at)

    assert str(raised.value) == "This request has expired."
    assert entry.status == EntryStatus.EXPIRED
    [message] = await messages(session)
    assert (message.thread_id, message.text, message.model) == (
        thread.id,
        "Expired: Creating a task: Buy milk.",
        None,
    )
    assert message.tool_calls is not None
    assert message.tool_calls[0]["status"] == "expired"


async def test_an_expired_request_says_so_again_without_a_new_message(
    session: AsyncSession,
) -> None:
    """Expiry 3."""
    user = await new_user(session)
    thread = await create_thread(session, user.id)
    entry = await new_request(session, user, thread.id, status=EntryStatus.EXPIRED)

    with pytest.raises(AlreadyDecidedError) as raised:
        await reject(session, user.id, entry.id, LONG_AGO)

    assert str(raised.value) == "This request has expired."

    assert await messages(session) == []


async def test_a_new_turn_expires_only_its_threads_overdue_requests(
    session: AsyncSession,
) -> None:
    """Decision #125: the thread's own requests, past their deadline, still pending."""
    user = await new_user(session, "owner")
    other = await new_user(session, "other")
    thread = await create_thread(session, user.id)
    elsewhere = await create_thread(session, user.id)
    overdue = await new_request(session, user, thread.id, title="Buy milk")
    done = await new_request(session, user, thread.id, status=EntryStatus.DONE)
    in_another_thread = await new_request(session, user, elsewhere.id)
    others = await new_request(session, other, thread.id)
    deadline = others.created_at
    fresh = await new_request(session, user, thread.id, title="Buy bread")

    await expire_overdue(session, user.id, thread.id, deadline)

    assert overdue.status == EntryStatus.EXPIRED
    assert [done.status, in_another_thread.status, others.status, fresh.status] == [
        EntryStatus.DONE,
        EntryStatus.PENDING,
        EntryStatus.PENDING,
        EntryStatus.PENDING,
    ]
    assert [message.text for message in await messages(session)] == [
        "Expired: Creating a task: Buy milk."
    ]
