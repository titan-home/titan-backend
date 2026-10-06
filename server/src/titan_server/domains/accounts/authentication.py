"""Authentication: which device, if any, a request's token belongs to."""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from titan_server.domains.accounts.devices import hash_token
from titan_server.domains.accounts.models import Device

# NOTE: one limit for everyone; each user's own limit (decision #25) comes
# with the user settings.
IDLE_LIMIT = timedelta(days=90)


async def authenticate(session: AsyncSession, token: str) -> Device | None:
    """Return the active device holding token and mark it as used, or None.

    A device is active when it is not revoked and was used within IDLE_LIMIT
    (accounts.md, device tokens, criteria 5 and 8). The device comes with its
    user loaded, so callers can read device.user without another query.
    """
    device = await session.scalar(
        select(Device)
        .options(joinedload(Device.user))
        .where(
            Device.token_hash == hash_token(token),
            Device.revoked_at.is_(None),
            Device.last_used_at > func.now() - IDLE_LIMIT,
        )
    )
    if device is not None:
        device.last_used_at = func.now()
    return device
