"""Tests for /api/v1/approvals: listing and deciding requests (decision #118)."""

import dataclasses
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.agent import turn
from titan_server.agent.tool import ToolContext
from titan_server.agent.tools.tasks import CreateTaskInput, create_task
from titan_server.api.app import create_app
from titan_server.api.dependencies import get_session
from titan_server.domains.accounts.devices import sign_in
from titan_server.domains.accounts.models import User
from titan_server.domains.accounts.passwords import hash_password
from titan_server.domains.audit.models import (
    ActionClass,
    AuditEntry,
    Domain,
    EntryStatus,
    Mode,
)
from titan_server.domains.chat.models import Message
from titan_server.domains.chat.service import create_thread
from titan_server.domains.tasks import service as tasks_service
from titan_server.domains.tasks.models import Task

pytestmark = pytest.mark.anyio

PASSWORD = "correct horse"
APPROVALS = "/api/v1/approvals"


@pytest.fixture
async def owner(session: AsyncSession) -> User:
    user = User(username="owner", password_hash=hash_password(PASSWORD))
    session.add(user)
    await session.flush()
    return user


@pytest.fixture
async def other(session: AsyncSession) -> User:
    user = User(username="other", password_hash="$argon2id$v=19$placeholder")
    session.add(user)
    await session.flush()
    return user


@pytest.fixture
async def client(
    session: AsyncSession, owner: User
) -> AsyncIterator[httpx.AsyncClient]:
    """A client signed in as the owner; database work rolled back after the test."""
    _, token = await sign_in(session, "owner", PASSWORD, "laptop", None)

    async def test_session() -> AsyncIterator[AsyncSession]:
        # Kept if the route returns, rolled back if it raises, as get_session.
        async with session.begin_nested():
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = test_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client


async def new_request(
    session: AsyncSession,
    user: User,
    title: str = "Buy milk",
    tool: str = "create_task",
    status: EntryStatus = EntryStatus.PENDING,
    thread_id: uuid.UUID | None = None,
    age: timedelta | None = None,
) -> AuditEntry:
    """A stored create_task call that waits for approval, as the agent leaves it.

    age makes it that much older than now; otherwise the database dates it.
    """
    entry = AuditEntry(
        id=uuid.uuid4(),
        user_id=user.id,
        thread_id=thread_id,
        tool=tool,
        summary=f"Creating a task: {title}",
        mode=Mode.CONFIRM,
        action_class=ActionClass.WRITE_INTERNAL,
        domain=Domain.TASKS,
        input={"title": title},
        status=status,
    )
    if age is not None:
        entry.created_at = datetime.now(UTC) - age
    session.add(entry)
    # One flush per request: each gets its own created_at, so the order is known.
    await session.flush()
    return entry


async def titles(session: AsyncSession) -> list[str]:
    return list(await session.scalars(select(Task.title)))


async def test_approvals_need_a_signed_in_device(client: httpx.AsyncClient) -> None:
    response = await client.get(APPROVALS, headers={"Authorization": ""})

    assert response.status_code == 401


async def test_a_request_shows_its_summary_domain_and_class(
    client: httpx.AsyncClient, session: AsyncSession, owner: User
) -> None:
    """Approvals 1."""
    entry = await new_request(session, owner)

    response = await client.get(APPROVALS)

    assert response.status_code == 200
    [item] = response.json()["items"]
    assert item == {
        "id": str(entry.id),
        "tool": "create_task",
        "summary": "Creating a task: Buy milk",
        "domain": "tasks",
        "action_class": "write-internal",
        "status": "pending",
        "created_at": item["created_at"],
    }
    assert response.json()["next"] is None


async def test_the_list_pages_through_requests_oldest_first(
    client: httpx.AsyncClient, session: AsyncSession, owner: User
) -> None:
    entries = [await new_request(session, owner, title) for title in "abc"]

    first = (await client.get(APPROVALS, params={"limit": 2})).json()
    second = (
        await client.get(APPROVALS, params={"limit": 2, "after": first["next"]})
    ).json()

    assert [item["id"] for item in first["items"]] == [str(e.id) for e in entries[:2]]
    assert first["next"] is not None
    assert [item["id"] for item in second["items"]] == [str(entries[2].id)]
    assert second["next"] is None


async def test_only_the_users_own_pending_requests_are_listed(
    client: httpx.AsyncClient, session: AsyncSession, owner: User, other: User
) -> None:
    """Approvals 4: another user's requests are not shown."""
    mine = await new_request(session, owner)
    await new_request(session, owner, status=EntryStatus.DONE)
    await new_request(session, other)

    response = await client.get(APPROVALS)

    assert [item["id"] for item in response.json()["items"]] == [str(mine.id)]


async def test_a_limit_over_the_nodes_maximum_is_capped(
    client: httpx.AsyncClient,
    session: AsyncSession,
    owner: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision #83: a larger limit is capped, not refused."""
    monkeypatch.setenv("TITAN_DEFAULT_MAX_PAGE_SIZE", "2")
    for title in "abc":
        await new_request(session, owner, title)

    asked_for_more = await client.get(APPROVALS, params={"limit": 50})
    no_limit = await client.get(APPROVALS)

    assert asked_for_more.status_code == 200
    assert len(asked_for_more.json()["items"]) == 2
    assert asked_for_more.json()["next"] is not None
    assert len(no_limit.json()["items"]) == 2


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"limit": 0}, "query.limit"),
        ({"limit": -1}, "query.limit"),
        ({"after": "not a cursor"}, "query.after"),
    ],
)
async def test_a_bad_limit_or_cursor_is_refused(
    client: httpx.AsyncClient, params: dict[str, str | int], field: str
) -> None:
    response = await client.get(APPROVALS, params=params)

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    # The same shape as any invalid input: the field, never the value sent.
    assert [error["field"] for error in response.json()["errors"]] == [field]


async def test_approving_runs_the_call(
    client: httpx.AsyncClient, session: AsyncSession, owner: User
) -> None:
    entry = await new_request(session, owner)

    response = await client.post(f"{APPROVALS}/{entry.id}/approve")

    assert response.status_code == 200
    assert response.json()["id"] == str(entry.id)
    assert response.json()["status"] == "done"
    assert await titles(session) == ["Buy milk"]


async def create_then_fail(context: ToolContext, task: CreateTaskInput) -> str:
    await tasks_service.create_task(context.session, context.user_id, task.title)
    raise RuntimeError("the database is down")


FAILING = dataclasses.replace(create_task, name="failing", run=create_then_fail)


async def test_a_failed_run_answers_200_with_failed(
    client: httpx.AsyncClient,
    session: AsyncSession,
    owner: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The outcome is in the status; the run's rollback must not break the answer."""
    monkeypatch.setattr(turn, "TOOLS", (*turn.TOOLS, FAILING))
    thread = await create_thread(session, owner.id)
    entry = await new_request(session, owner, tool="failing", thread_id=thread.id)

    response = await client.post(f"{APPROVALS}/{entry.id}/approve")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["summary"] == "Creating a task: Buy milk"
    assert await titles(session) == []


async def test_rejecting_tells_the_thread(
    client: httpx.AsyncClient, session: AsyncSession, owner: User
) -> None:
    thread = await create_thread(session, owner.id)
    entry = await new_request(session, owner, thread_id=thread.id)

    response = await client.post(f"{APPROVALS}/{entry.id}/reject")

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert await titles(session) == []
    texts = await session.scalars(
        select(Message.text).where(Message.thread_id == thread.id)
    )
    assert list(texts) == ["Rejected: Creating a task: Buy milk."]


@pytest.mark.parametrize("decision", ["approve", "reject"])
@pytest.mark.parametrize(
    ("whose", "status"),
    [
        ("another user's", EntryStatus.PENDING),
        # Not 409: its status must not reach anyone but its user.
        ("another user's", EntryStatus.DONE),
        ("missing", EntryStatus.PENDING),
    ],
)
async def test_another_users_request_is_not_found(
    client: httpx.AsyncClient,
    session: AsyncSession,
    other: User,
    decision: str,
    whose: str,
    status: EntryStatus,
) -> None:
    """Approvals 4: only the user whose agent made the request decides it."""
    entry = await new_request(session, other, status=status)
    entry_id = entry.id if whose == "another user's" else uuid.uuid4()

    response = await client.post(f"{APPROVALS}/{entry_id}/{decision}")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert "detail" not in response.json()
    assert await titles(session) == []


@pytest.mark.parametrize("second", ["approve", "reject"])
@pytest.mark.parametrize(
    ("first", "status", "tasks"),
    [("approve", "done", ["Buy milk"]), ("reject", "rejected", [])],
)
async def test_a_decided_request_is_not_decided_again(
    client: httpx.AsyncClient,
    session: AsyncSession,
    owner: User,
    first: str,
    status: str,
    tasks: list[str],
    second: str,
) -> None:
    """Approvals 3: a second Approve or Reject changes nothing (decision #121)."""
    entry = await new_request(session, owner)
    await client.post(f"{APPROVALS}/{entry.id}/{first}")

    response = await client.post(f"{APPROVALS}/{entry.id}/{second}")

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["detail"] == f"This request is already decided: {status}."
    assert await titles(session) == tasks


async def test_a_request_past_its_deadline_is_not_listed(
    client: httpx.AsyncClient, session: AsyncSession, owner: User
) -> None:
    """Expiry 1: a request lives 24 hours by default (decision #127)."""
    await new_request(session, owner, "Buy milk", age=timedelta(hours=25))
    fresh = await new_request(session, owner, "Buy bread", age=timedelta(hours=23))

    response = await client.get(APPROVALS)

    assert [item["id"] for item in response.json()["items"]] == [str(fresh.id)]


async def test_the_lifetime_is_the_nodes_setting(
    client: httpx.AsyncClient,
    session: AsyncSession,
    owner: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expiry 1: the node setting changes the lifetime of requests already waiting."""
    await new_request(session, owner, age=timedelta(hours=2))
    monkeypatch.setenv("TITAN_DEFAULT_APPROVAL_EXPIRY_HOURS", "1")

    response = await client.get(APPROVALS)

    assert response.json()["items"] == []


@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_deciding_an_expired_request_answers_409_and_keeps_the_mark(
    client: httpx.AsyncClient, session: AsyncSession, owner: User, decision: str
) -> None:
    """Expiry 2 to 4: it never runs, says it has expired, and its thread is told."""
    thread = await create_thread(session, owner.id)
    entry = await new_request(
        session, owner, thread_id=thread.id, age=timedelta(hours=25)
    )

    response = await client.post(f"{APPROVALS}/{entry.id}/{decision}")

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["detail"] == "This request has expired."
    # Kept although the answer is an error (decision #125).
    await session.refresh(entry)
    assert entry.status == EntryStatus.EXPIRED
    texts = await session.scalars(select(Message.text))
    assert list(texts) == ["Expired: Creating a task: Buy milk."]
    assert await titles(session) == []
