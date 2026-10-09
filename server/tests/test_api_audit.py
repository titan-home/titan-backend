"""Tests for /api/v1/audit: the log and undoing from it (decisions #135, #136)."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.agent.tool import ToolContext, sdk_tool
from titan_server.agent.tools.tasks import create_task
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
from titan_server.domains.tasks.models import Task

pytestmark = pytest.mark.anyio

PASSWORD = "correct horse"
ENTRIES = "/api/v1/audit/entries"


@pytest.fixture
async def owner(session: AsyncSession) -> User:
    user = User(username="owner", password_hash=hash_password(PASSWORD))
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


async def buy_milk(session: AsyncSession, user: User) -> AuditEntry:
    """The agent's call of create_task in the default auto-undo mode."""
    context = ToolContext(session=session, user_id=user.id, thread_id=None)
    await sdk_tool(create_task, context).handler({"title": "Buy milk"})
    entry = await session.scalar(
        select(AuditEntry).where(AuditEntry.user_id == user.id)
    )
    assert entry is not None
    return entry


async def new_entry(session: AsyncSession, user: User) -> AuditEntry:
    """A stored create_task call that ran."""
    entry = AuditEntry(
        user_id=user.id,
        tool="create_task",
        summary="Creating a task: Buy milk",
        mode=Mode.AUTO_UNDO,
        action_class=ActionClass.WRITE_INTERNAL,
        domain=Domain.TASKS,
        input={"title": "Buy milk"},
        undoable=True,
        status=EntryStatus.DONE,
    )
    session.add(entry)
    # One flush per entry: each gets its own created_at, in order.
    await session.flush()
    return entry


async def test_undo_needs_a_signed_in_device(client: httpx.AsyncClient) -> None:
    response = await client.post(
        f"{ENTRIES}/{uuid.uuid4()}/undo", headers={"Authorization": ""}
    )

    assert response.status_code == 401


async def test_undoing_answers_with_the_undos_entry(
    client: httpx.AsyncClient, session: AsyncSession, owner: User
) -> None:
    """Undo 4: the created task goes to the trash."""
    entry = await buy_milk(session, owner)

    response = await client.post(f"{ENTRIES}/{entry.id}/undo")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "id": body["id"],
        "tool": "undo",
        "summary": "Undo: Creating a task: Buy milk",
        "domain": "tasks",
        "action_class": "write-internal",
        "mode": None,
        "status": "done",
        "undoable": True,
        "undoes_entry_id": str(entry.id),
        "created_at": body["created_at"],
    }
    [task] = await session.scalars(select(Task))
    await session.refresh(task)
    assert task.deleted_at is not None


async def test_a_refused_undo_answers_409_with_why(
    client: httpx.AsyncClient, session: AsyncSession, owner: User
) -> None:
    """Decision #135: every refusal is 409 with a plain detail."""
    entry = await buy_milk(session, owner)
    await client.post(f"{ENTRIES}/{entry.id}/undo")

    response = await client.post(f"{ENTRIES}/{entry.id}/undo")

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["detail"] == "Cannot undo: this action is already undone."


@pytest.mark.parametrize("whose", ["another user's", "missing"])
async def test_another_users_entry_is_not_found(
    client: httpx.AsyncClient, session: AsyncSession, whose: str
) -> None:
    """Audit log 3: a user sees only their own log."""
    other = User(username="other", password_hash="$argon2id$v=19$placeholder")
    session.add(other)
    await session.flush()
    entry = await buy_milk(session, other)
    entry_id = entry.id if whose == "another user's" else uuid.uuid4()

    response = await client.post(f"{ENTRIES}/{entry_id}/undo")

    assert response.status_code == 404
    # Nothing about the entry, not even that it exists.
    assert "detail" not in response.json()
    [task] = await session.scalars(select(Task))
    await session.refresh(task)
    assert task.deleted_at is None


async def test_an_id_that_is_not_a_uuid_is_refused(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(f"{ENTRIES}/not-an-id/undo")

    assert response.status_code == 422


async def test_the_list_needs_a_signed_in_device(client: httpx.AsyncClient) -> None:
    response = await client.get(ENTRIES, headers={"Authorization": ""})

    assert response.status_code == 401


async def test_the_list_shows_every_entry_newest_first_undos_included(
    client: httpx.AsyncClient, session: AsyncSession, owner: User
) -> None:
    """Decision #136: calls of every status and undos, newest first."""
    entry = await buy_milk(session, owner)
    undo = (await client.post(f"{ENTRIES}/{entry.id}/undo")).json()

    response = await client.get(ENTRIES)

    assert response.status_code == 200
    [newer, older] = response.json()["items"]
    assert newer == undo
    assert (older["id"], older["tool"], older["status"]) == (
        str(entry.id),
        "create_task",
        "done",
    )
    assert response.json()["next"] is None


async def test_an_overdue_pending_request_is_listed_as_expired(
    client: httpx.AsyncClient, session: AsyncSession, owner: User
) -> None:
    """Decision #125: requests expire lazily, so the list checks the age."""
    overdue = await new_entry(session, owner)
    overdue.status = EntryStatus.PENDING
    overdue.created_at = datetime.now(UTC) - timedelta(hours=25)
    fresh = await new_entry(session, owner)
    fresh.status = EntryStatus.PENDING
    await session.flush()

    response = await client.get(ENTRIES)

    assert response.status_code == 200
    statuses = {item["id"]: item["status"] for item in response.json()["items"]}
    assert statuses == {str(overdue.id): "expired", str(fresh.id): "pending"}
    # Read only: the stored status is not changed by a GET.
    assert overdue.status == EntryStatus.PENDING


async def test_the_list_pages_through_entries_newest_first(
    client: httpx.AsyncClient, session: AsyncSession, owner: User
) -> None:
    entries = [await new_entry(session, owner) for _ in range(3)]

    first = (await client.get(ENTRIES, params={"limit": 2})).json()
    second = (
        await client.get(ENTRIES, params={"limit": 2, "after": first["next"]})
    ).json()

    newest_first = [str(entry.id) for entry in reversed(entries)]
    assert [item["id"] for item in first["items"]] == newest_first[:2]
    assert first["next"] is not None
    assert [item["id"] for item in second["items"]] == newest_first[2:]
    assert second["next"] is None


async def test_only_the_users_own_entries_are_listed(
    client: httpx.AsyncClient, session: AsyncSession, owner: User
) -> None:
    """Audit log 3: a user sees only their own log."""
    other = User(username="other", password_hash="$argon2id$v=19$placeholder")
    session.add(other)
    await session.flush()
    await new_entry(session, other)
    mine = await new_entry(session, owner)

    response = await client.get(ENTRIES)

    assert [item["id"] for item in response.json()["items"]] == [str(mine.id)]


async def test_a_limit_over_the_nodes_maximum_is_capped(
    client: httpx.AsyncClient,
    session: AsyncSession,
    owner: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision #83: a larger limit is capped, not refused."""
    monkeypatch.setenv("TITAN_DEFAULT_MAX_PAGE_SIZE", "2")
    for _ in range(3):
        await new_entry(session, owner)

    asked_for_more = await client.get(ENTRIES, params={"limit": 50})
    no_limit = await client.get(ENTRIES)

    assert asked_for_more.status_code == 200
    assert len(asked_for_more.json()["items"]) == 2
    assert asked_for_more.json()["next"] is not None
    assert len(no_limit.json()["items"]) == 2


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"limit": 0}, "query.limit"),
        ({"after": "not a cursor"}, "query.after"),
    ],
)
async def test_a_bad_limit_or_cursor_is_refused(
    client: httpx.AsyncClient, params: dict[str, str | int], field: str
) -> None:
    response = await client.get(ENTRIES, params=params)

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert [error["field"] for error in response.json()["errors"]] == [field]
