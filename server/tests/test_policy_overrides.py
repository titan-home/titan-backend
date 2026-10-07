"""Tests for a user's own modes per domain (autonomy spec, defaults; #114, #116)."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.domains.accounts.models import User
from titan_server.domains.audit.models import ActionClass, Domain, Mode
from titan_server.domains.policy.models import PolicyOverride
from titan_server.domains.policy.service import get_override

pytestmark = pytest.mark.anyio


async def new_user(session: AsyncSession, username: str = "owner") -> User:
    user = User(username=username, password_hash="$argon2id$v=19$placeholder")
    session.add(user)
    await session.flush()
    return user


def override(user: User, action_class: ActionClass, mode: Mode) -> PolicyOverride:
    return PolicyOverride(
        user_id=user.id, domain=Domain.TASKS, action_class=action_class, mode=mode
    )


async def test_a_users_own_mode_is_found(session: AsyncSession) -> None:
    user = await new_user(session)
    session.add(override(user, ActionClass.WRITE_INTERNAL, Mode.CONFIRM))
    await session.flush()

    found = await get_override(
        session, user.id, Domain.TASKS, ActionClass.WRITE_INTERNAL
    )

    assert found == Mode.CONFIRM


async def test_a_class_without_a_mode_of_its_own_has_none(
    session: AsyncSession,
) -> None:
    user = await new_user(session)
    session.add(override(user, ActionClass.WRITE_INTERNAL, Mode.CONFIRM))
    await session.flush()

    assert await get_override(session, user.id, Domain.TASKS, ActionClass.READ) is None


async def test_a_users_mode_applies_only_to_that_user(session: AsyncSession) -> None:
    """Defaults 3."""
    user = await new_user(session, "owner")
    other = await new_user(session, "other")
    session.add(override(user, ActionClass.WRITE_INTERNAL, Mode.DENY))
    await session.flush()

    found = await get_override(
        session, other.id, Domain.TASKS, ActionClass.WRITE_INTERNAL
    )

    assert found is None


async def test_one_class_in_one_domain_has_one_mode(session: AsyncSession) -> None:
    user = await new_user(session)
    session.add(override(user, ActionClass.WRITE_INTERNAL, Mode.CONFIRM))
    await session.flush()
    session.add(override(user, ActionClass.WRITE_INTERNAL, Mode.DENY))

    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.parametrize(
    "action_class", [ActionClass.EXTERNAL, ActionClass.DESTRUCTIVE]
)
@pytest.mark.parametrize("mode", [Mode.AUTO, Mode.AUTO_UNDO])
async def test_what_cannot_be_taken_back_is_never_set_below_confirm(
    session: AsyncSession, action_class: ActionClass, mode: Mode
) -> None:
    """Defaults 5; decision #116."""
    user = await new_user(session)
    session.add(override(user, action_class, mode))

    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.parametrize(
    "action_class", [ActionClass.EXTERNAL, ActionClass.DESTRUCTIVE]
)
async def test_what_cannot_be_taken_back_can_be_denied(
    session: AsyncSession, action_class: ActionClass
) -> None:
    user = await new_user(session)
    session.add(override(user, action_class, Mode.DENY))
    await session.flush()

    assert await get_override(session, user.id, Domain.TASKS, action_class) == Mode.DENY
