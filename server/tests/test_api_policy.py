"""Tests for /api/v1/policy/modes: a user's own modes (decisions #116, #117)."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.api.app import create_app
from titan_server.api.dependencies import get_session
from titan_server.domains.accounts.devices import sign_in
from titan_server.domains.accounts.models import User
from titan_server.domains.accounts.passwords import hash_password
from titan_server.domains.audit.models import ActionClass, Domain, Mode
from titan_server.domains.policy.models import PolicyOverride

pytestmark = pytest.mark.anyio

PASSWORD = "correct horse"
MODES = "/api/v1/policy/modes"


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    """A client signed in as the owner; database work rolled back after the test."""
    session.add(User(username="owner", password_hash=hash_password(PASSWORD)))
    await session.flush()
    _, token = await sign_in(session, "owner", PASSWORD, "laptop", None)

    async def test_session() -> AsyncIterator[AsyncSession]:
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


async def modes(client: httpx.AsyncClient) -> dict[tuple[str, str], dict[str, Any]]:
    response = await client.get(MODES)
    assert response.status_code == 200
    return {(row["domain"], row["action_class"]): row for row in response.json()}


async def test_the_modes_need_a_signed_in_device(client: httpx.AsyncClient) -> None:
    response = await client.get(MODES, headers={"Authorization": ""})

    assert response.status_code == 401


async def test_every_class_starts_at_its_default(client: httpx.AsyncClient) -> None:
    """Defaults 1."""
    found = await modes(client)

    assert {key: (row["mode"], row["own"]) for key, row in found.items()} == {
        ("tasks", "read"): ("auto", False),
        ("tasks", "write-internal"): ("auto-undo", False),
        ("tasks", "external"): ("confirm", False),
        ("tasks", "destructive"): ("confirm", False),
    }


async def test_a_user_sets_a_mode_of_their_own(client: httpx.AsyncClient) -> None:
    """Defaults 2: confirm for write-internal in one domain."""
    response = await client.put(
        f"{MODES}/tasks/write-internal", json={"mode": "confirm"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "domain": "tasks",
        "action_class": "write-internal",
        "mode": "confirm",
        "own": True,
    }
    found = await modes(client)
    assert found[("tasks", "write-internal")]["own"] is True
    assert found[("tasks", "read")]["own"] is False


@pytest.mark.parametrize("action_class", ["external", "destructive"])
@pytest.mark.parametrize("mode", ["auto", "auto-undo"])
async def test_what_cannot_be_taken_back_is_never_set_below_confirm(
    client: httpx.AsyncClient, action_class: str, mode: str
) -> None:
    """Defaults 5; decision #116."""
    response = await client.put(f"{MODES}/tasks/{action_class}", json={"mode": mode})

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert "confirm or deny" in response.json()["detail"]
    assert (await modes(client))[("tasks", action_class)]["own"] is False


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("tasks/write-internal", {"mode": "sometimes"}),
        ("finance/write-internal", {"mode": "confirm"}),
        ("tasks/write", {"mode": "confirm"}),
    ],
)
async def test_an_unknown_mode_domain_or_class_is_refused(
    client: httpx.AsyncClient, path: str, body: dict[str, str]
) -> None:
    response = await client.put(f"{MODES}/{path}", json=body)

    assert response.status_code == 422


async def test_resetting_returns_a_class_to_its_default(
    client: httpx.AsyncClient,
) -> None:
    await client.put(f"{MODES}/tasks/write-internal", json={"mode": "confirm"})

    response = await client.delete(f"{MODES}/tasks/write-internal")

    assert response.status_code == 204
    found = await modes(client)
    assert (
        found[("tasks", "write-internal")]["mode"],
        found[("tasks", "write-internal")]["own"],
    ) == ("auto-undo", False)


async def test_resetting_a_default_changes_nothing(client: httpx.AsyncClient) -> None:
    response = await client.delete(f"{MODES}/tasks/read")

    assert response.status_code == 204


async def test_another_users_modes_are_not_shown(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """Defaults 3."""
    other = User(username="other", password_hash="$argon2id$v=19$placeholder")
    session.add(other)
    await session.flush()
    session.add(
        PolicyOverride(
            user_id=other.id,
            domain=Domain.TASKS,
            action_class=ActionClass.WRITE_INTERNAL,
            mode=Mode.DENY,
        )
    )
    await session.flush()

    found = await modes(client)

    assert found[("tasks", "write-internal")]["own"] is False
