"""Tests for a chat turn, with scripted replies instead of Claude (chat.md)."""

import asyncio
import re
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    Message,
    ResultMessage,
    SdkMcpTool,
    StreamEvent,
    TextBlock,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from titan_api.agent.turn import (
    HISTORY_LIMIT,
    ReplyStored,
    TextDelta,
    ToolCalled,
    TurnEvent,
    TurnFailedError,
    prompt,
    run_turn,
    system_prompt,
)
from titan_core.domains.accounts.models import User
from titan_core.domains.audit.models import (
    ActionClass,
    AuditChange,
    AuditEntry,
    Domain,
    EntryStatus,
    Mode,
)
from titan_core.domains.chat import service as chat
from titan_core.domains.chat.models import Message as ChatMessage
from titan_core.domains.chat.models import Role, Thread, ToolCallRecord
from titan_core.domains.policy.service import set_override
from titan_core.domains.tasks.models import Task

pytestmark = pytest.mark.anyio

# Requests made after it have not expired: nothing in these tests is that old.
LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)

NOW = datetime(2026, 10, 7, 9, 30, tzinfo=UTC)
MODEL = "claude-opus-5-5"
USAGE = {
    "input_tokens": 1200,
    "output_tokens": 40,
    "cache_creation_input_tokens": 900,
    "cache_read_input_tokens": 300,
}


def text_delta(text: str) -> StreamEvent:
    event = {
        "type": "content_block_delta",
        "delta": {"type": "text_delta", "text": text},
    }
    return StreamEvent(uuid="e", session_id="s", event=event)


def result(*, is_error: bool = False) -> ResultMessage:
    return ResultMessage(
        subtype="error_during_execution" if is_error else "success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=is_error,
        num_turns=1,
        session_id="s",
        usage=USAGE,
    )


class Claude:
    """Plays Claude: calls the tools it is told to, then replies with a script."""

    def __init__(
        self, calls: Sequence[tuple[str, dict[str, Any]]] = (), reply: str = "Added."
    ) -> None:
        self.calls = calls
        self.reply = reply
        self.asked: list[tuple[str, str, list[str]]] = []

    async def __call__(
        self, system_prompt: str, prompt: str, tools: Sequence[SdkMcpTool[Any]]
    ) -> AsyncIterator[Message]:
        self.asked.append((system_prompt, prompt, [tool.name for tool in tools]))
        by_name = {tool.name: tool for tool in tools}
        for name, arguments in self.calls:
            await by_name[name].handler(arguments)
            yield AssistantMessage(content=[], model=MODEL)
        for word in self.reply.split(" "):
            yield text_delta(word)
        yield AssistantMessage(content=[TextBlock(self.reply)], model=MODEL)
        yield result()


async def new_thread(session: AsyncSession, username: str = "owner") -> Thread:
    user = User(username=username, password_hash="$argon2id$v=19$placeholder")
    session.add(user)
    await session.flush()
    return await chat.create_thread(session, user.id)


async def turn(
    session: AsyncSession, thread: Thread, text: str, claude: Claude
) -> list[TurnEvent]:
    events = run_turn(
        session, thread.user_id, thread.id, text, NOW, LONG_AGO, ask=claude
    )
    return [event async for event in events]


async def test_add_a_task_to_buy_milk(session: AsyncSession) -> None:
    """Stage 2: the reply streams, the task is in the database."""
    thread = await new_thread(session)
    claude = Claude(calls=[("create_task", {"title": "Buy milk"})], reply="Added it.")

    events = await turn(session, thread, "add a task to buy milk", claude)

    [task] = await session.scalars(select(Task).where(Task.user_id == thread.user_id))
    assert task.title == "Buy milk"
    [entry] = await session.scalars(select(AuditEntry))
    call: ToolCallRecord = {
        "name": "create_task",
        "summary": "Creating a task: Buy milk",
        "status": "done",
        "ok": True,
        "entry_id": str(entry.id),
        "domain": "tasks",
        "action_class": "write-internal",
        "mode": "auto-undo",
    }
    assert events[:-1] == [ToolCalled(call), TextDelta("Added"), TextDelta("it.")]
    assert isinstance(events[-1], ReplyStored)
    [question, reply] = await chat.history(session, thread)
    assert (question.role, question.text) == (Role.USER, "add a task to buy milk")
    assert (reply.id, reply.role, reply.text) == (
        events[-1].reply_id,
        Role.ASSISTANT,
        "Added it.",
    )
    assert reply.tool_calls == [call]


async def test_the_call_is_in_the_audit_log_with_the_whole_task(
    session: AsyncSession,
) -> None:
    """Stage 3: the entry knows its thread (decision #112) and keeps the row."""
    thread = await new_thread(session)
    claude = Claude(calls=[("create_task", {"title": "Buy milk"})], reply="Added it.")

    await turn(session, thread, "add a task to buy milk", claude)

    [task] = await session.scalars(select(Task).where(Task.user_id == thread.user_id))
    [entry] = await session.scalars(select(AuditEntry))
    assert (entry.thread_id, entry.tool, entry.status) == (
        thread.id,
        "create_task",
        EntryStatus.DONE,
    )
    [change] = await session.scalars(
        select(AuditChange).where(AuditChange.entry_id == entry.id)
    )
    assert (change.table_name, change.object_id, change.before, change.version) == (
        "tasks",
        task.id,
        None,
        1,
    )
    assert change.after is not None
    assert change.after["title"] == "Buy milk"


async def test_the_reply_keeps_its_model_and_tokens(session: AsyncSession) -> None:
    """Token usage 1."""
    thread = await new_thread(session)

    await turn(session, thread, "hello", Claude(reply="Hi."))

    [_, reply] = await chat.history(session, thread)
    assert (
        reply.model,
        reply.input_tokens,
        reply.output_tokens,
        reply.cache_write_tokens,
        reply.cache_read_tokens,
    ) == (MODEL, 1200, 40, 900, 300)


async def test_claude_gets_the_tools_and_the_bare_first_message(
    session: AsyncSession,
) -> None:
    thread = await new_thread(session)
    claude = Claude()

    await turn(session, thread, "hello", claude)

    [(_, prompt, tools)] = claude.asked
    assert (prompt, tools) == ("hello", ["create_task"])


async def test_later_turns_retell_the_thread_with_its_tool_calls(
    session: AsyncSession,
) -> None:
    """Decision #96: the history goes to Claude as text."""
    thread = await new_thread(session)
    await turn(
        session,
        thread,
        "add a task to buy milk",
        Claude(calls=[("create_task", {"title": "Buy milk"})], reply="Added it."),
    )
    claude = Claude(reply="It is on your list.")

    await turn(session, thread, "is it there?", claude)

    [(_, prompt, _)] = claude.asked
    assert prompt == (
        "<earlier_messages>\n"
        '<message role="user">\nadd a task to buy milk\n</message>\n'
        '<message role="assistant">\nAdded it.\n'
        "[create_task: Creating a task: Buy milk, done]\n</message>\n"
        "</earlier_messages>\n\n"
        "is it there?"
    )


@pytest.mark.parametrize(
    ("mode", "outcome"),
    [(Mode.CONFIRM, "waiting for approval"), (Mode.DENY, "not allowed")],
)
async def test_a_call_that_did_not_run_is_retold_as_it_stood(
    session: AsyncSession, mode: Mode, outcome: str
) -> None:
    """Decision #119: a waiting call is not retold as failed."""
    thread = await new_thread(session)
    await set_override(
        session, thread.user_id, Domain.TASKS, ActionClass.WRITE_INTERNAL, mode
    )
    await turn(
        session,
        thread,
        "add a task to buy milk",
        Claude(calls=[("create_task", {"title": "Buy milk"})]),
    )
    claude = Claude()

    await turn(session, thread, "is it there?", claude)

    [(_, prompt, _)] = claude.asked
    assert f"[create_task: Creating a task: Buy milk, {outcome}]\n" in prompt


async def test_a_new_turn_first_expires_the_threads_overdue_requests(
    session: AsyncSession,
) -> None:
    """Expiry 4 (decision #125): Claude reads that the call will not run."""
    thread = await new_thread(session)
    await set_override(
        session, thread.user_id, Domain.TASKS, ActionClass.WRITE_INTERNAL, Mode.CONFIRM
    )
    await turn(
        session,
        thread,
        "add a task to buy milk",
        Claude(calls=[("create_task", {"title": "Buy milk"})], reply="It waits."),
    )
    [entry] = await session.scalars(select(AuditEntry))
    claude = Claude(reply="It expired.")

    # A deadline at the request's creation time is already past.
    events = run_turn(
        session,
        thread.user_id,
        thread.id,
        "is it there?",
        NOW,
        entry.created_at,
        claude,
    )
    [event async for event in events]

    assert entry.status == EntryStatus.EXPIRED
    [(_, prompt, _)] = claude.asked
    assert prompt == (
        "<earlier_messages>\n"
        '<message role="user">\nadd a task to buy milk\n</message>\n'
        '<message role="assistant">\nIt waits.\n'
        "[create_task: Creating a task: Buy milk, waiting for approval]\n</message>\n"
        '<message role="assistant">\nExpired: Creating a task: Buy milk.\n'
        "[create_task: Creating a task: Buy milk, expired]\n</message>\n"
        "</earlier_messages>\n\n"
        "is it there?"
    )


async def test_a_call_stored_without_a_status_is_retold_from_ok(
    session: AsyncSession,
) -> None:
    """Replies stored before decision #119 keep only ok."""
    thread = await new_thread(session)
    await chat.add_user_message(session, thread, "add two tasks")
    stored: list[ToolCallRecord] = [
        {"name": "create_task", "summary": "Creating a task: Buy milk", "ok": True},
        {"name": "create_task", "summary": "Creating a task: Buy rye", "ok": False},
    ]
    await chat.add_reply(
        session, thread, "Added one.", stored, chat.Usage(MODEL, 0, 0, 0, 0)
    )
    claude = Claude()

    await turn(session, thread, "which?", claude)

    [(_, prompt, _)] = claude.asked
    assert (
        "[create_task: Creating a task: Buy milk, done]\n"
        "[create_task: Creating a task: Buy rye, failed]\n"
    ) in prompt


def retold(status: str) -> str:
    """The history retold for a reply that keeps one call with status."""
    reply = ChatMessage(
        role=Role.ASSISTANT,
        text="Rejected: Creating a task: Buy milk.",
        tool_calls=[
            {
                "name": "create_task",
                "summary": "Creating a task: Buy milk",
                "status": status,
                "ok": False,
            }
        ],
    )
    return prompt([reply], "and now?")


@pytest.mark.parametrize("status", list(EntryStatus))
def test_every_status_of_an_entry_has_a_retelling(status: EntryStatus) -> None:
    """Node-written messages store rejected and expired too (decisions #120, #126)."""
    assert re.search(
        r"\[create_task: Creating a task: Buy milk, [a-z ]+\]\n", retold(status)
    )


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        ("done", "done"),
        ("failed", "failed"),
        ("pending", "waiting for approval"),
        ("denied", "not allowed"),
        ("rejected", "rejected"),
        ("expired", "expired"),
        # A record never breaks the turns after it, whatever it holds.
        ("archived", "archived"),
    ],
)
def test_a_stored_call_is_retold_by_its_status(status: str, outcome: str) -> None:
    assert f"[create_task: Creating a task: Buy milk, {outcome}]\n" in retold(status)


async def test_a_call_in_confirm_waits_for_approval(session: AsyncSession) -> None:
    """Modes 4 and decision #119: the call does not run and the reply says so."""
    thread = await new_thread(session)
    await set_override(
        session,
        thread.user_id,
        Domain.TASKS,
        ActionClass.WRITE_INTERNAL,
        Mode.CONFIRM,
    )
    claude = Claude(calls=[("create_task", {"title": "Buy milk"})], reply="Approve?")

    events = await turn(session, thread, "add a task to buy milk", claude)

    assert list(await session.scalars(select(Task))) == []
    [entry] = await session.scalars(select(AuditEntry))
    assert entry.status == EntryStatus.PENDING
    call: ToolCallRecord = {
        "name": "create_task",
        "summary": "Creating a task: Buy milk",
        "status": "pending",
        "ok": False,
        "entry_id": str(entry.id),
        "domain": "tasks",
        "action_class": "write-internal",
        "mode": "confirm",
    }
    assert events[0] == ToolCalled(call)
    [_, reply] = await chat.history(session, thread)
    assert reply.tool_calls == [call]


async def test_only_the_latest_messages_are_retold(session: AsyncSession) -> None:
    thread = await new_thread(session)
    for number in range(HISTORY_LIMIT + 5):
        await chat.add_user_message(session, thread, f"message {number}")
    claude = Claude()

    await turn(session, thread, "and now?", claude)

    [(_, prompt, _)] = claude.asked
    assert prompt.count("<message ") == HISTORY_LIMIT
    assert "message 4\n" not in prompt
    assert f"message {HISTORY_LIMIT + 4}\n" in prompt


async def test_the_system_prompt_ends_with_the_time_it_was_given() -> None:
    """Decision #97: what changes comes last; the time is never read from a clock."""
    prompt = system_prompt(NOW)

    assert prompt.rstrip().endswith(
        "The current time is 2026-10-07 09:30 UTC; the user's time zone is UTC."
    )


async def test_the_system_prompt_asks_for_the_language_of_the_last_message() -> None:
    """Replies in the language of the message 1 and 2; checked live by the owner."""
    prompt = system_prompt(NOW)

    assert "language of the user's last message" in prompt
    assert "main one" in prompt


async def test_another_users_thread_is_not_found_and_claude_is_not_asked(
    session: AsyncSession,
) -> None:
    """Threads 1."""
    thread = await new_thread(session, "owner")
    other = User(username="other", password_hash="$argon2id$v=19$placeholder")
    session.add(other)
    await session.flush()
    claude = Claude()

    with pytest.raises(chat.ThreadNotFoundError):
        events = run_turn(
            session, other.id, thread.id, "hello", NOW, LONG_AGO, ask=claude
        )
        [event async for event in events]

    assert claude.asked == []
    assert await chat.history(session, thread) == []


async def test_a_turn_claude_did_not_finish_stores_no_reply(
    session: AsyncSession,
) -> None:
    thread = await new_thread(session)

    async def failing(
        system_prompt: str, prompt: str, tools: Sequence[SdkMcpTool[Any]]
    ) -> AsyncIterator[Message]:
        yield text_delta("Add")
        yield result(is_error=True)

    with pytest.raises(TurnFailedError):
        [
            event
            async for event in run_turn(
                session, thread.user_id, thread.id, "hi", NOW, LONG_AGO, failing
            )
        ]

    replies = await session.scalars(
        select(ChatMessage).where(ChatMessage.role == Role.ASSISTANT)
    )
    assert list(replies) == []


async def test_a_missing_thread_is_not_found(session: AsyncSession) -> None:
    thread = await new_thread(session)

    with pytest.raises(chat.ThreadNotFoundError):
        events = run_turn(
            session, thread.user_id, uuid.uuid4(), "hi", NOW, LONG_AGO, Claude()
        )
        [event async for event in events]


async def test_a_tool_call_comes_before_the_text_written_after_it(
    session: AsyncSession,
) -> None:
    """Tool activity 1: the call shows where it happened in the reply."""
    thread = await new_thread(session)

    async def claude(
        system_prompt: str, prompt: str, tools: Sequence[SdkMcpTool[Any]]
    ) -> AsyncIterator[Message]:
        # Claude Code streams the text after a tool call with no whole
        # message in between.
        await tools[0].handler({"title": "Buy milk"})
        yield text_delta("Added.")
        yield AssistantMessage(content=[TextBlock("Added.")], model=MODEL)
        yield result()

    events = [
        event
        async for event in run_turn(
            session, thread.user_id, thread.id, "hi", NOW, LONG_AGO, claude
        )
    ]

    assert [type(event) for event in events] == [ToolCalled, TextDelta, ReplyStored]


async def test_a_tool_call_is_reported_only_once_it_has_finished(
    session: AsyncSession,
) -> None:
    """Tool activity 1: a call that worked is never shown as failed."""
    thread = await new_thread(session)

    async def claude(
        system_prompt: str, prompt: str, tools: Sequence[SdkMcpTool[Any]]
    ) -> AsyncIterator[Message]:
        # The SDK runs a tool in a task of its own and keeps streaming while
        # the tool waits for the database.
        running = asyncio.ensure_future(tools[0].handler({"title": "Buy milk"}))
        await asyncio.sleep(0)
        yield StreamEvent(uuid="e", session_id="s", event={"type": "ping"})
        await running
        yield text_delta("Added.")
        yield AssistantMessage(content=[TextBlock("Added.")], model=MODEL)
        yield result()

    # Each call as it was when reported, before the turn goes on.
    reported = [
        dict(event.call)
        async for event in run_turn(
            session, thread.user_id, thread.id, "hi", NOW, LONG_AGO, claude
        )
        if isinstance(event, ToolCalled)
    ]

    [entry] = await session.scalars(select(AuditEntry))
    assert reported == [
        {
            "name": "create_task",
            "summary": "Creating a task: Buy milk",
            "status": "done",
            "ok": True,
            "entry_id": str(entry.id),
            "domain": "tasks",
            "action_class": "write-internal",
            "mode": "auto-undo",
        }
    ]
