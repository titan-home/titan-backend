"""Tests for POST /api/v1/devices: signing in over HTTP."""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from titan_api.app import create_app
from titan_api.dependencies import get_session
from titan_api.guessing import GuessingLimit
from titan_core.domains.accounts.devices import TOKEN_PREFIX
from titan_core.domains.accounts.models import User
from titan_core.domains.accounts.passwords import MAX_PASSWORD_LENGTH, hash_password

pytestmark = pytest.mark.anyio


class Clock:
    """A clock the test moves by hand, in seconds."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
async def users(session: AsyncSession) -> None:
    """The accounts owner and other, both with the password correct horse."""
    for username in ("owner", "other"):
        password_hash = hash_password("correct horse")
        session.add(User(username=username, password_hash=password_hash))
    await session.flush()


def api(session: AsyncSession, clock: Clock) -> FastAPI:
    """The API on the test's session and clock, its database work rolled back."""

    async def test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app = create_app()
    app.dependency_overrides[get_session] = test_session
    app.state.guessing_limit = GuessingLimit(clock)
    return app


def connect(app: FastAPI, address: str = "127.0.0.1") -> httpx.AsyncClient:
    """An HTTP client for app whose connection comes from address."""
    transport = httpx.ASGITransport(app=app, client=(address, 50000))
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
async def app(session: AsyncSession, clock: Clock, users: None) -> FastAPI:
    return api(session, clock)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client for the API, its database work rolled back after the test."""
    async with connect(app) as client:
        yield client


def credentials(
    password: str = "correct horse", username: str = "owner"
) -> dict[str, str]:
    return {"username": username, "password": password, "name": "laptop"}


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


async def fail_ten_times(
    client: httpx.AsyncClient, headers: dict[str, str] | None = None
) -> None:
    for _ in range(10):
        response = await client.post(
            "/api/v1/devices", json=credentials("wrong horse"), headers=headers
        )
        assert response.status_code == 401


async def test_ten_failures_refuse_the_right_and_the_wrong_password_alike(
    client: httpx.AsyncClient, clock: Clock
) -> None:
    """Accounts spec, guessing limit 1 and 3; sign in 3: failures count."""
    await fail_ten_times(client)
    clock.now += 60

    right = await client.post("/api/v1/devices", json=credentials())
    wrong = await client.post("/api/v1/devices", json=credentials("wrong horse"))

    assert right.status_code == 429
    assert right.headers["retry-after"] == str(15 * 60 - 60)
    assert right.headers["content-type"] == "application/problem+json"
    assert (wrong.status_code, wrong.headers, wrong.text) == (
        right.status_code,
        right.headers,
        right.text,
    )


async def test_a_refused_pair_signs_in_once_the_window_passed(
    client: httpx.AsyncClient, clock: Clock
) -> None:
    """Accounts spec, guessing limit 1: refused for 15 minutes, not for good."""
    await fail_ten_times(client)
    clock.now += 15 * 60

    response = await client.post("/api/v1/devices", json=credentials())

    assert response.status_code == 201


async def test_the_account_stays_open_from_other_addresses(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """Accounts spec, guessing limit 1: only that pair is refused."""
    await fail_ten_times(client)

    async with connect(app, "198.51.100.7") as elsewhere:
        response = await elsewhere.post("/api/v1/devices", json=credentials())

    assert response.status_code == 201


async def test_other_accounts_stay_open_from_the_same_address(
    client: httpx.AsyncClient,
) -> None:
    """Accounts spec, guessing limit 1: only that pair is refused."""
    await fail_ten_times(client)

    response = await client.post("/api/v1/devices", json=credentials(username="other"))

    assert response.status_code == 201


async def test_x_forwarded_for_names_the_client_behind_a_trusted_proxy(
    session: AsyncSession,
    clock: Clock,
    users: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accounts spec, guessing limit 2: trusted from our own proxies."""
    monkeypatch.setenv("TITAN_TRUSTED_PROXIES", "10.0.0.0/8")
    app = api(session, clock)

    async with connect(app, "10.0.0.2") as proxy:
        await fail_ten_times(proxy, {"X-Forwarded-For": "203.0.113.5"})
        refused = await proxy.post(
            "/api/v1/devices",
            json=credentials(),
            headers={"X-Forwarded-For": "203.0.113.5"},
        )
        elsewhere = await proxy.post(
            "/api/v1/devices",
            json=credentials(),
            headers={"X-Forwarded-For": "203.0.113.6"},
        )

    assert refused.status_code == 429
    assert elsewhere.status_code == 201


async def test_x_forwarded_for_is_ignored_from_anyone_else(
    session: AsyncSession,
    clock: Clock,
    users: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accounts spec, guessing limit 2: otherwise the connection's address counts."""
    monkeypatch.setenv("TITAN_TRUSTED_PROXIES", "10.0.0.0/8")
    app = api(session, clock)

    async with connect(app, "198.51.100.7") as client:
        for number in range(10):
            response = await client.post(
                "/api/v1/devices",
                json=credentials("wrong horse"),
                headers={"X-Forwarded-For": f"203.0.113.{number}"},
            )
            assert response.status_code == 401
        refused = await client.post(
            "/api/v1/devices",
            json=credentials(),
            headers={"X-Forwarded-For": "203.0.113.99"},
        )

    assert refused.status_code == 429


def test_the_contract_declares_retry_after_for_a_refused_sign_in() -> None:
    """Accounts spec, guessing limit 3: 429 with Retry-After."""
    responses = create_app().openapi()["paths"]["/api/v1/devices"]["post"]["responses"]

    header = responses["429"]["headers"]["Retry-After"]
    assert header["schema"] == {"type": "integer"}
    assert header["description"]


async def test_the_right_most_untrusted_address_is_the_client(
    session: AsyncSession,
    clock: Clock,
    users: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accounts spec, guessing limit 2: only our own proxies are believed.

    A client may send its own X-Forwarded-For; our proxy appends the address
    it saw, so the right-most entry it did not add is the real client.
    """
    monkeypatch.setenv("TITAN_TRUSTED_PROXIES", "10.0.0.2")
    app = api(session, clock)
    forged = {"X-Forwarded-For": "198.51.100.1, 203.0.113.5"}

    async with connect(app, "10.0.0.2") as proxy:
        await fail_ten_times(proxy, forged)
        refused = await proxy.post(
            "/api/v1/devices",
            json=credentials(),
            headers={"X-Forwarded-For": "203.0.113.5"},
        )
        named = await proxy.post(
            "/api/v1/devices",
            json=credentials(),
            headers={"X-Forwarded-For": "198.51.100.1"},
        )

    assert refused.status_code == 429
    assert named.status_code == 201


async def test_x_forwarded_for_is_ignored_without_trusted_proxies(
    session: AsyncSession,
    clock: Clock,
    users: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accounts spec, guessing limit 2: otherwise the connection's address counts."""
    monkeypatch.delenv("TITAN_TRUSTED_PROXIES", raising=False)
    app = api(session, clock)

    async with connect(app, "10.0.0.2") as client:
        for number in range(10):
            response = await client.post(
                "/api/v1/devices",
                json=credentials("wrong horse"),
                headers={"X-Forwarded-For": f"203.0.113.{number}"},
            )
            assert response.status_code == 401
        refused = await client.post(
            "/api/v1/devices",
            json=credentials(),
            headers={"X-Forwarded-For": "203.0.113.99"},
        )

    assert refused.status_code == 429
