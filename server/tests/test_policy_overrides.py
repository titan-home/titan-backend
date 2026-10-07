"""Tests for a user's own modes per domain (autonomy spec, defaults; #114, #116)."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.domains.accounts.models import User
from titan_server.domains.audit.models import ActionClass, Domain, Mode
from titan_server.domains.policy.models import PolicyOverride
from titan_server.domains.policy.service import (
    ModeBelowFloorError,
    get_override,
    set_override,
)

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


async def test_setting_a_mode_makes_it_the_users_own(session: AsyncSession) -> None:
    """Defaults 2."""
    user = await new_user(session)

    await set_override(
        session, user.id, Domain.TASKS, ActionClass.WRITE_INTERNAL, Mode.CONFIRM
    )

    found = await get_override(
        session, user.id, Domain.TASKS, ActionClass.WRITE_INTERNAL
    )
    assert found == Mode.CONFIRM


async def test_setting_a_mode_again_replaces_it(session: AsyncSession) -> None:
    user = await new_user(session)
    for mode in (Mode.CONFIRM, Mode.AUTO):
        await set_override(
            session, user.id, Domain.TASKS, ActionClass.WRITE_INTERNAL, mode
        )

    found = await get_override(
        session, user.id, Domain.TASKS, ActionClass.WRITE_INTERNAL
    )
    rows = await session.scalar(select(func.count()).select_from(PolicyOverride))
    assert (found, rows) == (Mode.AUTO, 1)


async def test_setting_a_mode_leaves_other_users_alone(session: AsyncSession) -> None:
    """Defaults 3."""
    user = await new_user(session, "owner")
    other = await new_user(session, "other")
    session.add(override(other, ActionClass.WRITE_INTERNAL, Mode.DENY))
    await session.flush()

    await set_override(
        session, user.id, Domain.TASKS, ActionClass.WRITE_INTERNAL, Mode.CONFIRM
    )

    found = await get_override(
        session, other.id, Domain.TASKS, ActionClass.WRITE_INTERNAL
    )
    assert found == Mode.DENY


@pytest.mark.parametrize(
    "action_class", [ActionClass.EXTERNAL, ActionClass.DESTRUCTIVE]
)
@pytest.mark.parametrize("mode", [Mode.AUTO, Mode.AUTO_UNDO])
async def test_setting_a_mode_below_the_floor_is_refused_before_the_database(
    session: AsyncSession, action_class: ActionClass, mode: Mode
) -> None:
    """Defaults 5: a clear error rather than the database's constraint."""
    user = await new_user(session)

    with pytest.raises(ModeBelowFloorError):
        await set_override(session, user.id, Domain.TASKS, action_class, mode)

    assert await get_override(session, user.id, Domain.TASKS, action_class) is None
