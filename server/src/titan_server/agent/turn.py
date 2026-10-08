"""A chat turn: the user's message in, Claude's reply streamed out and stored.

A plain async function rather than a graph (decision #99).
"""

import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import files
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    Message,
    ResultMessage,
    SdkMcpTool,
    StreamEvent,
    TextBlock,
)
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.agent.claude import ask_claude
from titan_server.agent.tool import Tool, ToolContext, sdk_tool
from titan_server.agent.tools.tasks import create_task
from titan_server.domains.audit import approvals
from titan_server.domains.chat import service as chat
from titan_server.domains.chat.models import Message as ChatMessage
from titan_server.domains.chat.models import ToolCallRecord

TOOLS: tuple[Tool[Any], ...] = (create_task,)
# NOTE: reads the whole thread and keeps the latest messages; fine for
# threads of a few hundred messages, ask the database for only the latest
# ones when it is not.
HISTORY_LIMIT = 40

Ask = Callable[[str, str, Sequence[SdkMcpTool[Any]]], AsyncIterator[Message]]


@dataclass(frozen=True)
class TextDelta:
    """The next piece of the reply's text, as Claude writes it."""

    text: str


@dataclass(frozen=True)
class ToolCalled:
    """A tool call, run or not, for the client to show (chat spec, tool activity)."""

    call: ToolCallRecord


@dataclass(frozen=True)
class ReplyStored:
    """The turn is over and its reply is in the thread."""

    reply_id: uuid.UUID


TurnEvent = TextDelta | ToolCalled | ReplyStored

# How the history retells a call's status (decision #119); any other status,
# such as done, failed, rejected or expired, is retold as it is, so a record
# never breaks the turns after it.
RETOLD_STATUS = {"pending": "waiting for approval", "denied": "not allowed"}


class TurnFailedError(Exception):
    """Claude did not finish the turn; the reason is in the message."""


def system_prompt(now: datetime) -> str:
    """The fixed prompt first, read from the cache, then what changes (decision #97)."""
    fixed = files("titan_server.agent").joinpath("system_prompt.md").read_text()
    # NOTE: the time zone is UTC until users have settings; then it is theirs.
    return (
        f"{fixed}\nThe current time is {now:%Y-%m-%d %H:%M} UTC;"
        " the user's time zone is UTC.\n"
    )


def prompt(earlier: Sequence[ChatMessage], text: str) -> str:
    """The thread's history, retold as text (decision #96), then the new message."""
    if not earlier:
        return text
    lines = ["<earlier_messages>"]
    for message in earlier:
        lines.append(f'<message role="{message.role}">')
        lines.append(message.text)
        for call in message.tool_calls or []:
            # A reply stored before decision #119 has only ok.
            status = call.get("status", "done" if call["ok"] else "failed")
            outcome = RETOLD_STATUS.get(status, status)
            lines.append(f"[{call['name']}: {call['summary']}, {outcome}]")
        lines.append("</message>")
    lines.append("</earlier_messages>")
    return "\n".join(lines) + "\n\n" + text


async def run_turn(
    session: AsyncSession,
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
    text: str,
    now: datetime,
    expired_before: datetime,
    ask: Ask = ask_claude,
) -> AsyncIterator[TurnEvent]:
    """Store the user's message, ask Claude with the tools, store the reply.

    The thread's requests past their deadline expire first, so Claude reads
    that they will not run (decision #125); expired_before is as for
    approvals.lock_pending. Raises ThreadNotFoundError for another user's
    thread and TurnFailedError when Claude does not finish. The caller
    commits the session.
    """
    thread = await chat.get_thread(session, user_id, thread_id)
    await approvals.expire_overdue(session, user_id, thread.id, expired_before)
    earlier = (await chat.history(session, thread))[-HISTORY_LIMIT:]
    await chat.add_user_message(session, thread, text)

    context = ToolContext(session=session, user_id=user_id, thread_id=thread.id)
    tools = [sdk_tool(tool, context) for tool in TOOLS]
    reported = 0
    texts: list[str] = []
    model = ""
    result: ResultMessage | None = None

    async for message in ask(system_prompt(now), prompt(earlier, text), tools):
        # Tools run while Claude works: report the calls that ran before this
        # message, so they come before the text written after them.
        for call in context.calls[reported:]:
            yield ToolCalled(call)
        reported = len(context.calls)
        if isinstance(message, StreamEvent):
            delta = message.event.get("delta", {})
            if delta.get("type") == "text_delta":
                yield TextDelta(delta["text"])
        elif isinstance(message, AssistantMessage):
            model = message.model
            texts += [
                block.text for block in message.content if isinstance(block, TextBlock)
            ]
        elif isinstance(message, ResultMessage):
            result = message

    if result is None or result.is_error:
        reason = "no result" if result is None else result.subtype
        raise TurnFailedError(f"Claude did not finish the turn: {reason}")

    usage = result.usage or {}
    reply = await chat.add_reply(
        session,
        thread,
        "\n\n".join(texts),
        context.calls,
        chat.Usage(
            model=model,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_write_tokens=usage.get("cache_creation_input_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
        ),
    )
    yield ReplyStored(reply.id)
