"""Tests for signing in (accounts.md, sign in and device tokens)."""

import base64
import hashlib
from datetime import UTC, datetime

import argon2
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.domains.accounts.devices import (
    TOKEN_PREFIX,
    InvalidCredentialsError,
    hash_token,
    new_token,
    sign_in,
)
from titan_server.domains.accounts.models import Device, User
from titan_server.domains.accounts.passwords import hash_password

pytestmark = pytest.mark.anyio


async def add_user(session: AsyncSession, username: str = "owner") -> User:
    user = User(username=username, password_hash=hash_password("correct horse"))
    session.add(user)
    await session.flush()
    return user


async def count_devices(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Device)) or 0


def test_a_token_is_the_prefix_and_32_random_bytes_in_base64url() -> None:
    # Device tokens, criterion 3 (decision #29).
    token = new_token()

    assert token.startswith(TOKEN_PREFIX)
    encoded = token.removeprefix(TOKEN_PREFIX)
    assert len(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))) == 32
    assert new_token() != token


def test_the_token_hash_is_its_sha256() -> None:
    assert hash_token("titan_v1_abc") == hashlib.sha256(b"titan_v1_abc").digest()


async def test_the_right_credentials_pair_a_new_device(session: AsyncSession) -> None:
    # Sign in, criterion 1; device tokens, criteria 1 and 4.
    user = await add_user(session)

    device, token = await sign_in(session, "owner", "correct horse", "laptop", None)
    await session.flush()

    assert device.user_id == user.id
    assert device.name == "laptop"
    assert token.startswith(TOKEN_PREFIX)
    assert device.token_hash == hash_token(token)
    assert await count_devices(session) == 1


@pytest.mark.parametrize(
    ("username", "password"),
    [("owner", "wrong horse"), ("nobody", "correct horse")],
)
async def test_wrong_credentials_are_refused_the_same_way(
    session: AsyncSession, username: str, password: str
) -> None:
    # Sign in, criterion 2.
    await add_user(session)

    with pytest.raises(InvalidCredentialsError):
        await sign_in(session, username, password, "laptop", None)
    await session.flush()

    assert await count_devices(session) == 0


async def test_nobody_signs_in_before_the_owner_exists(session: AsyncSession) -> None:
    # Create the owner, criterion 5.
    with pytest.raises(InvalidCredentialsError):
        await sign_in(session, "owner", "correct horse", "laptop", None)


async def test_an_unknown_username_still_costs_one_password_check(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Sign in, criterion 2: the time of the answer does not tell whether the
    # username exists. Time is not measured (rules, 8); Argon2 must run once.
    calls = []
    real_verify = argon2.PasswordHasher.verify

    def counting_verify(
        self: argon2.PasswordHasher, password_hash: str, password: str
    ) -> bool:
        calls.append(password_hash)
        return real_verify(self, password_hash, password)

    monkeypatch.setattr(argon2.PasswordHasher, "verify", counting_verify)

    with pytest.raises(InvalidCredentialsError):
        await sign_in(session, "nobody", "correct horse", "laptop", None)

    assert len(calls) == 1


async def test_signing_in_again_replaces_the_token_of_the_same_device(
    session: AsyncSession,
) -> None:
    # Device tokens, criterion 2 (decision #24).
    await add_user(session)
    first, old_token = await sign_in(session, "owner", "correct horse", "a", None)
    await session.flush()

    again, token = await sign_in(session, "owner", "correct horse", "a", old_token)
    await session.flush()

    assert again.id == first.id
    assert token != old_token
    assert again.token_hash == hash_token(token)
    assert await count_devices(session) == 1


async def test_an_unknown_old_token_pairs_a_new_device(session: AsyncSession) -> None:
    await add_user(session)
    await sign_in(session, "owner", "correct horse", "a", None)
    await session.flush()

    await sign_in(session, "owner", "correct horse", "b", new_token())
    await session.flush()

    assert await count_devices(session) == 2


async def test_a_revoked_device_is_not_paired_again(session: AsyncSession) -> None:
    await add_user(session)
    revoked, old_token = await sign_in(session, "owner", "correct horse", "a", None)
    revoked.revoked_at = datetime.now(UTC)
    await session.flush()

    device, _ = await sign_in(session, "owner", "correct horse", "a", old_token)
    await session.flush()

    assert device.id != revoked.id
    assert await count_devices(session) == 2


async def test_another_users_device_is_never_taken_over(
    session: AsyncSession,
) -> None:
    # Signing in with your own password and someone else's old token must not
    # hand you their device.
    await add_user(session, "owner")
    other_user = await add_user(session, "other")
    other_device = Device(
        user=other_user, name="their phone", token_hash=hash_token("titan_v1_theirs")
    )
    session.add(other_device)
    await session.flush()

    device, _ = await sign_in(
        session, "owner", "correct horse", "laptop", "titan_v1_theirs"
    )
    await session.flush()

    assert device.id != other_device.id
    assert other_device.token_hash == hash_token("titan_v1_theirs")
    assert await count_devices(session) == 2


async def test_signing_in_counts_as_using_the_device(session: AsyncSession) -> None:
    # The device list shows a device as used just now right after sign-in.
    await add_user(session)
    device, old_token = await sign_in(session, "owner", "correct horse", "a", None)
    await session.refresh(device)
    paired_at = device.last_used_at

    again, _ = await sign_in(session, "owner", "correct horse", "a", old_token)
    await session.refresh(again)

    assert paired_at is not None
    assert again.last_used_at is not None
    assert again.last_used_at >= paired_at
