"""Tests for how a Tool reaches the Agent SDK (decision #98)."""

import dataclasses
import uuid
from typing import Any, cast

import pytest
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.agent.tool import ActionClass, Tool, ToolContext, sdk_tool

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
    input_model=EchoInput,
    summary=lambda echo_input: f"Echoing {echo_input.word}",
    run=echo_run,
)


@pytest.fixture
def context() -> ToolContext:
    calls.clear()
    return ToolContext(session=cast(AsyncSession, None), user_id=uuid.uuid4())


def test_the_model_sees_the_name_description_and_input_schema(
    context: ToolContext,
) -> None:
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

    assert context.calls == [{"name": "echo", "summary": "Echoing milk", "ok": True}]


async def test_a_call_that_fails_is_recorded_as_failed(context: ToolContext) -> None:
    async def fail(context: ToolContext, echo_input: EchoInput) -> str:
        raise RuntimeError("the database is down")

    failing = dataclasses.replace(ECHO, run=fail)

    with pytest.raises(RuntimeError):
        await sdk_tool(failing, context).handler({"word": "milk"})

    assert context.calls == [{"name": "echo", "summary": "Echoing milk", "ok": False}]


@pytest.mark.parametrize("arguments", [{}, {"word": ""}, {"word": 5}])
async def test_invalid_input_is_an_error_for_the_model_and_runs_nothing(
    context: ToolContext, arguments: dict[str, Any]
) -> None:
    result = await sdk_tool(ECHO, context).handler(arguments)

    assert result["is_error"] is True
    assert calls == []
    assert context.calls == []
