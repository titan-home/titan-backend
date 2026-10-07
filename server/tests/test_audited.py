"""Tests for the Audited mixin (decisions #108, #110)."""

from typing import Any

import pytest
from sqlalchemy.exc import MissingGreenlet
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper

from titan_server.db import Audited, Base
from titan_server.domains.accounts.models import User
from titan_server.domains.tasks.models import Task
from titan_server.domains.tasks.service import create_task


def audited_tables() -> list[Mapper[Any]]:
    return [
        mapper for mapper in Base.registry.mappers if issubclass(mapper.class_, Audited)
    ]


def test_tasks_are_audited() -> None:
    assert Task in [table.class_ for table in audited_tables()]


def test_every_column_of_an_audited_table_keeps_its_old_value() -> None:
    # A primary key never changes, so it has no old value to keep.
    missing = [
        f"{table.class_.__name__}.{column.key}"
        for table in audited_tables()
        for column in table.column_attrs
        if not column.active_history and not column.columns[0].primary_key
    ]

    assert missing == []


async def new_task(session: AsyncSession) -> Task:
    user = User(username="owner", password_hash="$argon2id$v=19$placeholder")
    session.add(user)
    await session.flush()
    return await create_task(session, user.id, "Buy milk")


@pytest.mark.anyio
async def test_an_update_raises_the_version(session: AsyncSession) -> None:
    task = await new_task(session)
    await session.refresh(task)
    assert task.version == 1

    task.title = "Buy oat milk"
    await session.flush()

    assert task.version == 2


@pytest.mark.anyio
async def test_a_change_to_a_value_never_loaded_fails_rather_than_loses_it(
    session: AsyncSession,
) -> None:
    # Without active_history the change would go through with no old value,
    # and its undo would be lost silently. In an async session the old value
    # cannot be fetched on assignment, so the change fails instead.
    task = await new_task(session)
    session.expire(task, ["title"])

    with pytest.raises(MissingGreenlet):
        task.title = "Buy oat milk"
