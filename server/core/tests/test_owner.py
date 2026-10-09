"""Tests for creating the owner (accounts.md, create the owner at install time)."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from titan_core.domains.accounts.models import User
from titan_core.domains.accounts.models.user import MAX_USERNAME_LENGTH
from titan_core.domains.accounts.owner import (
    OwnerExistsError,
    PasswordTooShortError,
    UsernameInvalidError,
    create_owner,
)
from titan_core.domains.accounts.passwords import verify_password

pytestmark = pytest.mark.anyio


async def count_users(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(User)) or 0


async def test_creates_the_owner_with_a_password_hash(session: AsyncSession) -> None:
    # Criteria 1 and 2.
    owner = await create_owner(session, "owner", "correct horse")
    await session.flush()

    assert owner.username == "owner"
    assert owner.is_owner
    assert owner.password_hash != "correct horse"
    assert verify_password(owner.password_hash, "correct horse")
    assert await count_users(session) == 1


async def test_a_password_of_eight_characters_is_enough(session: AsyncSession) -> None:
    # Criterion 4.
    await create_owner(session, "owner", "12345678")
    await session.flush()

    assert await count_users(session) == 1


async def test_a_shorter_password_is_refused(session: AsyncSession) -> None:
    # Criterion 4.
    with pytest.raises(PasswordTooShortError):
        await create_owner(session, "owner", "1234567")
    await session.flush()

    assert await count_users(session) == 0


async def test_a_second_owner_is_refused_and_nothing_changes(
    session: AsyncSession,
) -> None:
    # Criterion 6.
    await create_owner(session, "owner", "correct horse")
    await session.flush()

    with pytest.raises(OwnerExistsError):
        await create_owner(session, "another", "correct horse")
    await session.flush()

    assert await count_users(session) == 1


async def test_a_username_of_the_maximum_length_is_accepted(
    session: AsyncSession,
) -> None:
    await create_owner(session, "x" * MAX_USERNAME_LENGTH, "correct horse")
    await session.flush()

    assert await count_users(session) == 1


@pytest.mark.parametrize("username", ["", "   ", "x" * (MAX_USERNAME_LENGTH + 1)])
async def test_an_empty_or_too_long_username_is_refused(
    session: AsyncSession, username: str
) -> None:
    with pytest.raises(UsernameInvalidError):
        await create_owner(session, username, "correct horse")
    await session.flush()

    assert await count_users(session) == 0
