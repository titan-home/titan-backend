"""Reading a user's own modes; every function acts for one user."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.domains.audit.models import ActionClass, Domain, Mode
from titan_server.domains.policy.models import PolicyOverride


async def get_override(
    session: AsyncSession, user_id: uuid.UUID, domain: Domain, action_class: ActionClass
) -> Mode | None:
    """The user's own mode for action_class in domain, or None if they set none."""
    mode: Mode | None = await session.scalar(
        select(PolicyOverride.mode).where(
            PolicyOverride.user_id == user_id,
            PolicyOverride.domain == domain,
            PolicyOverride.action_class == action_class,
        )
    )
    return mode
