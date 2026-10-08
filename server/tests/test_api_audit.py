"""Tests for /api/v1/audit: undoing an action from its entry (decision #135)."""

import uuid
from collections.abc import AsyncIterator

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
from titan_server.domains.audit.models import AuditEntry
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
