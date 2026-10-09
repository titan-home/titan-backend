"""Tests for the users and devices tables (shared/docs/product/domains/accounts.md)."""

import hashlib
import secrets
import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from titan_core.domains.accounts.models import Device, User

pytestmark = pytest.mark.anyio


def new_user(username: str = "owner") -> User:
    return User(username=username, password_hash="$argon2id$v=19$placeholder")


def new_device(user: User, token: bytes = b"token") -> Device:
    return Device(user=user, name="laptop", token_hash=hashlib.sha256(token).digest())


async def test_ids_are_uuids_from_the_application(session: AsyncSession) -> None:
    user = new_user()
    device = new_device(user)
    session.add_all([user, device])
    await session.flush()

    assert isinstance(user.id, uuid.UUID)
    assert isinstance(device.id, uuid.UUID)


async def test_times_are_stored_with_a_time_zone(session: AsyncSession) -> None:
    user = new_user()
    device = new_device(user)
    session.add_all([user, device])
    await session.flush()
    await session.refresh(user)
    await session.refresh(device)

    assert user.created_at.tzinfo is not None
    assert device.created_at.tzinfo is not None


async def test_usernames_are_unique(session: AsyncSession) -> None:
    session.add_all([new_user("owner"), new_user("owner")])

    with pytest.raises(IntegrityError):
        await session.flush()


async def test_token_hashes_are_unique(session: AsyncSession) -> None:
    user = new_user()
    session.add_all([new_device(user, b"same"), new_device(user, b"same")])

    with pytest.raises(IntegrityError):
        await session.flush()


async def test_a_device_belongs_to_an_existing_user(session: AsyncSession) -> None:
    session.add(
        Device(
            user_id=uuid.uuid4(),
            name="laptop",
            token_hash=hashlib.sha256(secrets.token_bytes(32)).digest(),
        )
    )

    with pytest.raises(IntegrityError):
        await session.flush()
