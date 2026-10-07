"""Tests for how a Tool reaches the Agent SDK (decision #98)."""

import dataclasses
import uuid
from typing import Any, cast

import pytest
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.agent import policy
from titan_server.agent.tool import Tool, ToolContext, sdk_tool
from titan_server.domains.accounts.models import User
from titan_server.domains.audit.models import (
    ActionClass,
    AuditEntry,
    Domain,
    EntryStatus,
    Mode,
)

pytestmark = pytest.mark.anyio


class EchoInput(BaseModel):
    word: str = Field(min_length=1, description="The word to echo.")


calls: list[tuple[ToolContext, EchoInput]] = []


async def echo_run(context: ToolContext, echo_input: EchoInput) -> str:
    calls.append((context, echo_input))
    return f"echo {echo_input.word}"


ECHO = Tool(
    name="echo",
    description="Repeat a word.",
    action_class=ActionClass.READ,
    domain=Domain.TASKS,
    undoable=False,
    input_model=EchoInput,
    summary=lambda echo_input: f"Echoing {echo_input.word}",
    run=echo_run,
)


@pytest.fixture
async def context(session: AsyncSession) -> ToolContext:
    """A call made by a real user, outside a chat."""
    calls.clear()
    user = User(username="owner", password_hash="$argon2id$v=19$placeholder")
    session.add(user)
    await session.flush()
    return ToolContext(session=session, user_id=user.id, thread_id=None)


async def entries(context: ToolContext) -> list[AuditEntry]:
    return list(await context.session.scalars(select(AuditEntry)))


def test_the_model_sees_the_name_description_and_input_schema() -> None:
    context = ToolContext(
        session=cast(AsyncSession, None), user_id=uuid.uuid4(), thread_id=None
    )
    sdk = sdk_tool(ECHO, context)

    assert (sdk.name, sdk.description) == ("echo", "Repeat a word.")
    assert sdk.input_schema == EchoInput.model_json_schema()


async def test_a_valid_call_runs_for_the_context_and_returns_text(
    context: ToolContext,
) -> None:
    result = await sdk_tool(ECHO, context).handler({"word": "milk"})

    assert result == {"content": [{"type": "text", "text": "echo milk"}]}
    assert calls == [(context, EchoInput(word="milk"))]


async def test_every_call_is_recorded_with_its_summary_and_outcome(
    context: ToolContext,
) -> None:
    """Chat spec, tool activity 1: name, summary and whether it succeeded."""
    await sdk_tool(ECHO, context).handler({"word": "milk"})

    [entry] = await entries(context)
    assert context.calls == [
        {
            "name": "echo",
            "summary": "Echoing milk",
            "ok": True,
            "entry_id": str(entry.id),
        }
    ]


async def test_every_call_is_written_to_the_audit_log(context: ToolContext) -> None:
    """Autonomy spec, audit log 1: when, which tool, its class, input, outcome."""
    await sdk_tool(ECHO, context).handler({"word": "milk"})

    [entry] = await entries(context)
    assert (
        entry.user_id,
        entry.thread_id,
        entry.tool,
        entry.action_class,
        entry.input,
        entry.summary,
        entry.status,
    ) == (
        context.user_id,
        None,
        "echo",
        ActionClass.READ,
        {"word": "milk"},
        "Echoing milk",
        EntryStatus.DONE,
    )
    assert entry.mode == Mode.AUTO


async def test_a_call_that_fails_is_recorded_as_failed(context: ToolContext) -> None:
    async def fail(context: ToolContext, echo_input: EchoInput) -> str:
        raise RuntimeError("the database is down")

    failing = dataclasses.replace(ECHO, run=fail)

    with pytest.raises(RuntimeError):
        await sdk_tool(failing, context).handler({"word": "milk"})

    [entry] = await entries(context)
    assert entry.status == EntryStatus.FAILED
    assert context.calls == [
        {
            "name": "echo",
            "summary": "Echoing milk",
            "ok": False,
            "entry_id": str(entry.id),
        }
    ]


@pytest.mark.parametrize("arguments", [{}, {"word": ""}, {"word": 5}])
async def test_invalid_input_is_an_error_for_the_model_and_runs_nothing(
    context: ToolContext, arguments: dict[str, Any]
) -> None:
    result = await sdk_tool(ECHO, context).handler(arguments)

    assert result["is_error"] is True
    assert calls == []
    assert context.calls == []
    # The model's mistake, not a call: nothing ran, so nothing is logged.
    assert await entries(context) == []


async def test_a_call_that_needs_approval_does_not_run_and_waits(
    context: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Modes 4: confirm does not run; the call becomes an approval request."""
    monkeypatch.setitem(policy.DEFAULT_MODES, ActionClass.READ, Mode.CONFIRM)

    result = await sdk_tool(ECHO, context).handler({"word": "milk"})

    assert calls == []
    [entry] = await entries(context)
    assert (entry.mode, entry.status) == (Mode.CONFIRM, EntryStatus.PENDING)
    # The model is told the call is waiting, which is not an error.
    assert not result.get("is_error")
    assert "approval" in result["content"][0]["text"]


async def test_a_denied_call_does_not_run_and_the_model_is_told(
    context: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Modes 5: deny does not run, and the agent is told it is not allowed."""
    monkeypatch.setitem(policy.DEFAULT_MODES, ActionClass.READ, Mode.DENY)

    result = await sdk_tool(ECHO, context).handler({"word": "milk"})

    assert calls == []
    [entry] = await entries(context)
    assert (entry.mode, entry.status) == (Mode.DENY, EntryStatus.DENIED)
    assert result["is_error"] is True
    assert "not allowed" in result["content"][0]["text"]
