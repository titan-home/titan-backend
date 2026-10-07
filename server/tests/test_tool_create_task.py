"""Tests for the create_task tool (tasks.md, tasks 1, 2 and 5; decision #38)."""

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.agent.tool import ToolContext, sdk_tool
from titan_server.agent.tools.tasks import CreateTaskInput, create_task
from titan_server.domains.accounts.models import User
from titan_server.domains.audit.models import (
    ActionClass,
    AuditEntry,
    Domain,
    EntryStatus,
    Mode,
)
from titan_server.domains.policy.models import PolicyOverride
from titan_server.domains.tasks.models import Task, TaskStatus

pytestmark = pytest.mark.anyio


async def new_user(session: AsyncSession, username: str = "owner") -> User:
    user = User(username=username, password_hash="$argon2id$v=19$placeholder")
    session.add(user)
    await session.flush()
    return user


async def call(
    session: AsyncSession, user: User, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Call the tool the way the Agent SDK does, for user."""
    context = ToolContext(session=session, user_id=user.id, thread_id=None)
    return await sdk_tool(create_task, context).handler(arguments)


async def tasks_of(session: AsyncSession, user: User) -> list[Task]:
    return list(await session.scalars(select(Task).where(Task.user_id == user.id)))


async def test_creates_an_open_task_for_the_caller(session: AsyncSession) -> None:
    user = await new_user(session)

    result = await call(session, user, {"title": "Buy milk"})

    [task] = await tasks_of(session, user)
    assert (task.title, task.status) == ("Buy milk", TaskStatus.OPEN)
    assert not result.get("is_error")
    assert "Buy milk" in result["content"][0]["text"]


async def test_the_model_cannot_create_a_task_for_another_user(
    session: AsyncSession,
) -> None:
    """Tasks 5; development rules, section 14: a tool checks access."""
    user = await new_user(session, "owner")
    other = await new_user(session, "other")

    await call(session, user, {"title": "Buy milk", "user_id": str(other.id)})

    assert await tasks_of(session, other) == []


@pytest.mark.parametrize("arguments", [{}, {"title": ""}, {"title": "   "}])
async def test_a_task_without_a_title_is_refused(
    session: AsyncSession, arguments: dict[str, Any]
) -> None:
    user = await new_user(session)

    result = await call(session, user, arguments)

    assert result["is_error"] is True
    assert await tasks_of(session, user) == []


def test_creating_a_task_is_an_internal_write() -> None:
    """Decision #38: write-internal runs at once, with an Undo, from stage 3."""
    assert create_task.action_class == ActionClass.WRITE_INTERNAL


def test_the_summary_names_the_task() -> None:
    summary = create_task.summary(CreateTaskInput.model_validate({"title": "Buy milk"}))

    assert "Buy milk" in summary
    assert "\n" not in summary


def test_the_model_reads_a_description_of_the_tool_and_every_field() -> None:
    schema = CreateTaskInput.model_json_schema()

    assert "TODO" not in create_task.description
    assert schema["required"] == ["title"]
    assert all(field.get("description") for field in schema["properties"].values())


async def test_a_user_who_wants_to_approve_task_writes_gets_a_waiting_call(
    session: AsyncSession,
) -> None:
    """Defaults 2: confirm for write-internal in tasks, for this user only."""
    user = await new_user(session)
    session.add(
        PolicyOverride(
            user_id=user.id,
            domain=Domain.TASKS,
            action_class=ActionClass.WRITE_INTERNAL,
            mode=Mode.CONFIRM,
        )
    )
    await session.flush()

    await call(session, user, {"title": "Buy milk"})

    assert await tasks_of(session, user) == []
    [entry] = await session.scalars(select(AuditEntry))
    assert (entry.mode, entry.status) == (Mode.CONFIRM, EntryStatus.PENDING)


def test_creating_a_task_works_in_the_tasks_domain() -> None:
    assert create_task.domain == Domain.TASKS
