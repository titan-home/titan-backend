"""Tests for finding the device of a token (accounts.md, device tokens)."""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, text
from sqlalchemy.ext.asyncio import AsyncSession

from titan_api.dependencies import CurrentDevice, get_session
from titan_api.problems import add_problem_handlers
from titan_core.domains.accounts.authentication import authenticate
from titan_core.domains.accounts.devices import hash_token
from titan_core.domains.accounts.models import Device, User

pytestmark = pytest.mark.anyio

TOKEN = "titan_v1_known"


@pytest.fixture
async def device(session: AsyncSession) -> Device:
    user = User(username="owner", password_hash="$argon2id$placeholder")
    device = Device(
        user=user, name="laptop", token_hash=hash_token(TOKEN), last_used_at=func.now()
    )
    session.add(device)
    await session.flush()
    return device


async def age(session: AsyncSession, device: Device, days: int) -> None:
    await session.execute(
        text("UPDATE devices SET last_used_at = now() - make_interval(days => :days)"),
        {"days": days},
    )
    await session.refresh(device)


async def test_a_known_token_finds_its_device(
    session: AsyncSession, device: Device
) -> None:
    found = await authenticate(session, TOKEN)

    assert found is device
    assert found.user.username == "owner"


async def test_using_a_token_marks_the_device_as_used(
    session: AsyncSession, device: Device
) -> None:
    await age(session, device, 10)
    before = device.last_used_at

    await authenticate(session, TOKEN)
    await session.flush()
    await session.refresh(device)

    assert before is not None
    assert device.last_used_at is not None
    assert device.last_used_at > before


async def test_an_unknown_token_finds_nothing(
    session: AsyncSession, device: Device
) -> None:
    # Device tokens, criterion 5.
    assert await authenticate(session, "titan_v1_unknown") is None


async def test_a_revoked_device_finds_nothing(
    session: AsyncSession, device: Device
) -> None:
    # Device tokens, criterion 5; list devices, criterion 2.
    device.revoked_at = func.now()
    await session.flush()

    assert await authenticate(session, TOKEN) is None


async def test_a_token_unused_for_90_days_has_expired(
    session: AsyncSession, device: Device
) -> None:
    # Device tokens, criterion 8 (decision #25).
    await age(session, device, 89)
    assert await authenticate(session, TOKEN) is not None

    await age(session, device, 91)
    assert await authenticate(session, TOKEN) is None


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    add_problem_handlers(app)

    @app.get("/whose")
    async def whose(device: CurrentDevice) -> dict[str, str]:
        return {"name": device.name}

    async def test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = test_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_a_route_gets_the_device_of_the_bearer_token(
    client: httpx.AsyncClient, device: Device
) -> None:
    response = await client.get("/whose", headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 200
    assert response.json() == {"name": "laptop"}


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer titan_v1_unknown"}, {"Authorization": "Basic x"}],
)
async def test_no_valid_token_answers_401(
    client: httpx.AsyncClient, device: Device, headers: dict[str, str]
) -> None:
    response = await client.get("/whose", headers=headers)

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["www-authenticate"] == "Bearer"
