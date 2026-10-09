"""Devices: signing in pairs a device and gives it a token."""

import asyncio
import base64
import hashlib
import secrets

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from titan_core.domains.accounts.models import Device, User
from titan_core.domains.accounts.passwords import verify_password

TOKEN_PREFIX = "titan_v1_"  # noqa: S105  a prefix, not a secret


class InvalidCredentialsError(Exception):
    """The username or the password is wrong; which one is never told."""


def new_token() -> str:
    """Make a new device token: TOKEN_PREFIX and 32 random bytes in base64url."""
    random_bytes = secrets.token_bytes(32)
    b64_token = base64.urlsafe_b64encode(random_bytes).decode("utf-8")
    return TOKEN_PREFIX + b64_token.rstrip("=")


def hash_token(token: str) -> bytes:
    """Return the SHA-256 of token, the only form the node stores."""
    return hashlib.sha256(token.encode("utf-8")).digest()


async def sign_in(
    session: AsyncSession,
    username: str,
    password: str,
    name: str,
    old_token: str | None,
) -> tuple[Device, str]:
    """Check the credentials, pair or re-pair the device, return it and its token."""
    user = await session.scalar(select(User).where(User.username == username))
    password_hash = user.password_hash if user is not None else None
    verified_password = await asyncio.to_thread(
        verify_password, password_hash, password
    )
    if (user is None) or (not verified_password):
        raise InvalidCredentialsError

    device = None
    if old_token is not None:
        old_token_hash = hash_token(old_token)
        device = await session.scalar(
            select(Device).where(
                Device.token_hash == old_token_hash,
                Device.user_id == user.id,
                Device.revoked_at.is_(None),
            )
        )

    token = new_token()
    token_hash = hash_token(token)
    if device is not None:
        device.token_hash = token_hash
    else:
        device = Device(user_id=user.id, name=name, token_hash=token_hash)
        session.add(device)
    # Signing in is a use: the device list shows it as used just now.
    device.last_used_at = func.now()

    await session.flush()
    return device, token
