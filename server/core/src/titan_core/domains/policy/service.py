"""A user's own modes per domain; every function acts for one user."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from titan_core.domains.audit.models import ActionClass, Domain, Mode
from titan_core.domains.policy.models import PolicyOverride

# Decision #38; no class defaults to deny.
DEFAULT_MODES: dict[ActionClass, Mode] = {
    ActionClass.READ: Mode.AUTO,
    ActionClass.WRITE_INTERNAL: Mode.AUTO_UNDO,
    ActionClass.EXTERNAL: Mode.CONFIRM,
    ActionClass.DESTRUCTIVE: Mode.CONFIRM,
}

# What cannot be taken back always passes a person (decision #116).
FLOOR: dict[ActionClass, frozenset[Mode]] = {
    ActionClass.EXTERNAL: frozenset({Mode.CONFIRM, Mode.DENY}),
    ActionClass.DESTRUCTIVE: frozenset({Mode.CONFIRM, Mode.DENY}),
}


class ModeBelowFloorError(Exception):
    """external and destructive are never set below confirm (decision #116)."""


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


async def set_override(
    session: AsyncSession,
    user_id: uuid.UUID,
    domain: Domain,
    action_class: ActionClass,
    mode: Mode,
) -> None:
    """Make mode the user's own for action_class in domain, replacing any earlier.

    Raises ModeBelowFloorError for a mode the class may not have.
    """
    allowed_modes = FLOOR.get(action_class)
    if (allowed_modes is not None) and (mode not in allowed_modes):
        raise ModeBelowFloorError

    policy_override: PolicyOverride | None = await session.scalar(
        select(PolicyOverride).where(
            PolicyOverride.user_id == user_id,
            PolicyOverride.domain == domain,
            PolicyOverride.action_class == action_class,
        )
    )

    if policy_override is not None:
        policy_override.mode = mode
    else:
        policy_override = PolicyOverride(
            user_id=user_id, domain=domain, action_class=action_class, mode=mode
        )
        session.add(policy_override)

    await session.flush()


@dataclass(frozen=True)
class ModeInEffect:
    """The mode one action class runs in, in one domain, for one user."""

    domain: Domain
    action_class: ActionClass
    mode: Mode
    # The user's own mode rather than the default (decision #117).
    own: bool


async def modes_in_effect(
    session: AsyncSession, user_id: uuid.UUID
) -> list[ModeInEffect]:
    """The mode of every action class in every domain for the user."""
    overrides = await session.scalars(
        select(PolicyOverride).where(PolicyOverride.user_id == user_id)
    )
    own = {(row.domain, row.action_class): row.mode for row in overrides}
    return [
        ModeInEffect(
            domain=domain,
            action_class=action_class,
            mode=own.get((domain, action_class), DEFAULT_MODES[action_class]),
            own=(domain, action_class) in own,
        )
        for domain in Domain
        for action_class in ActionClass
    ]


async def reset_override(
    session: AsyncSession, user_id: uuid.UUID, domain: Domain, action_class: ActionClass
) -> None:
    """Return action_class in domain to its default mode for the user."""
    policy_override = await session.scalar(
        select(PolicyOverride).where(
            PolicyOverride.user_id == user_id,
            PolicyOverride.domain == domain,
            PolicyOverride.action_class == action_class,
        )
    )
    if policy_override is not None:
        await session.delete(policy_override)
        await session.flush()
