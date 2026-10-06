"""Tests for POST /api/v1/devices: signing in over HTTP."""

from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.api.app import create_app
from titan_server.api.dependencies import get_session
from titan_server.domains.accounts.devices import TOKEN_PREFIX
from titan_server.domains.accounts.models import User
from titan_server.domains.accounts.passwords import MAX_PASSWORD_LENGTH, hash_password

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client for the API, its database work rolled back after the test."""
    session.add(User(username="owner", password_hash=hash_password("correct horse")))
    await session.flush()

    async def test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app = create_app()
    app.dependency_overrides[get_session] = test_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def credentials(password: str = "correct horse") -> dict[str, str]:
    return {"username": "owner", "password": password, "name": "laptop"}


async def test_signing_in_pairs_a_device(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/devices", json=credentials())

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "name", "token"}
    assert body["name"] == "laptop"
    assert body["token"].startswith(TOKEN_PREFIX)


async def test_wrong_credentials_answer_401(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/devices", json=credentials("wrong horse"))

    assert response.status_code == 401
    assert "correct horse" not in response.text
    assert "wrong horse" not in response.text


async def test_a_huge_password_is_refused_before_hashing(
    client: httpx.AsyncClient,
) -> None:
    password = "x" * (MAX_PASSWORD_LENGTH + 1)
    response = await client.post("/api/v1/devices", json=credentials(password))

    assert response.status_code == 422
    assert password not in response.text


async def sign_in_over_http(
    client: httpx.AsyncClient, old_token: str | None = None
) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {old_token}"} if old_token else {}
    response = await client.post("/api/v1/devices", json=credentials(), headers=headers)
    assert response.status_code == 201
    body: dict[str, str] = response.json()
    return body


async def test_signing_in_again_with_the_old_token_keeps_the_device(
    client: httpx.AsyncClient,
) -> None:
    # Device tokens, criterion 2 (decision #24).
    first = await sign_in_over_http(client)

    again = await sign_in_over_http(client, first["token"])

    assert again["id"] == first["id"]
    assert again["token"] != first["token"]
    me = await client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {first['token']}"}
    )
    assert me.status_code == 401


async def test_whoami_tells_who_is_signed_in_on_this_device(
    client: httpx.AsyncClient,
) -> None:
    # Sign in, criterion 5.
    token = (await sign_in_over_http(client))["token"]

    response = await client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json() == {"username": "owner", "device": {"name": "laptop"}}


async def test_whoami_without_a_token_answers_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
