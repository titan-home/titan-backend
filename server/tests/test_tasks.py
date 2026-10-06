"""Tests for the tasks table and creating tasks (shared/.../domains/tasks.md)."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.domains.accounts.models import User
from titan_server.domains.tasks.models import TaskStatus
from titan_server.domains.tasks.service import create_task

pytestmark = pytest.mark.anyio


async def new_user(session: AsyncSession) -> User:
    user = User(username="owner", password_hash="$argon2id$v=19$placeholder")
    session.add(user)
    await session.flush()
    return user


async def test_a_new_task_is_open_and_belongs_to_the_user(
    session: AsyncSession,
) -> None:
    user = await new_user(session)

    task = await create_task(session, user.id, "Buy milk")
    await session.refresh(task)

    assert isinstance(task.id, uuid.UUID)
    assert (task.user_id, task.title, task.status) == (
        user.id,
        "Buy milk",
        TaskStatus.OPEN,
    )
    assert task.created_at.tzinfo is not None


async def test_the_status_is_open_done_or_cancelled(session: AsyncSession) -> None:
    """Tasks 2."""
    user = await new_user(session)
    task = await create_task(session, user.id, "Buy milk")

    with pytest.raises(IntegrityError):
        await session.execute(
            text("UPDATE tasks SET status = 'later' WHERE id = :id"), {"id": task.id}
        )


async def test_a_task_belongs_to_an_existing_user(session: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        await create_task(session, uuid.uuid4(), "Buy milk")
