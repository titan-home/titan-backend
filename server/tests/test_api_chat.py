"""Tests for the chat API: threads and replies streamed as events (chat.md)."""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from titan_server.agent.turn import Ask
from titan_server.api.app import create_app
from titan_server.api.dependencies import background_sessions, get_session
from titan_server.api.v1 import chat as chat_api
from titan_server.domains.accounts.devices import sign_in
from titan_server.domains.accounts.models import User
from titan_server.domains.accounts.passwords import hash_password
from titan_server.domains.audit.models import AuditEntry
from titan_server.domains.chat import service as chat
from titan_server.domains.chat.models import Message as ChatMessage
from titan_server.domains.tasks.models import Task

pytestmark = pytest.mark.anyio

PASSWORD = "correct horse"
ADD_MILK = "add a task to buy milk"


def result(*, is_error: bool = False) -> ResultMessage:
    return ResultMessage(
        subtype="error_during_execution" if is_error else "success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=is_error,
        num_turns=1,
        session_id="s",
        usage={"input_tokens": 10, "output_tokens": 2},
    )


def text_delta(text: str) -> StreamEvent:
    event = {
        "type": "content_block_delta",
        "delta": {"type": "text_delta", "text": text},
    }
    return StreamEvent(uuid="e", session_id="s", event=event)


class Claude:
    """Plays Claude: creates the task, then writes "Added it." in two pieces."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.asked = 0

    async def __call__(
        self, system_prompt: str, prompt: str, tools: Sequence[SdkMcpTool[Any]]
    ) -> AsyncIterator[Message]:
        self.asked += 1
        [create_task] = tools
        await create_task.handler({"title": "Buy milk"})
        yield text_delta("Added ")
        yield text_delta("it.")
        yield AssistantMessage(
            content=[TextBlock("Added it.")], model="claude-opus-5-5"
        )
        yield result(is_error=self.fail)


@pytest.fixture
def claude() -> Claude:
    return Claude()


@pytest.fixture
async def client(
    session: AsyncSession, claude: Claude
) -> AsyncIterator[httpx.AsyncClient]:
    """A client signed in as the owner; database work rolled back after the test."""
    user = User(username="owner", password_hash=hash_password(PASSWORD))
    session.add(user)
    await session.flush()
    _, token = await sign_in(session, "owner", PASSWORD, "laptop", None)

    async def test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app = create_app()
    app.dependency_overrides[get_session] = test_session
    # A turn's own transaction becomes a savepoint inside the test's.
    app.dependency_overrides[background_sessions] = lambda: async_sessionmaker(
        bind=session.bind, join_transaction_mode="create_savepoint"
    )
    app.dependency_overrides[chat_api.claude] = lambda: claude
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client


async def new_thread(client: httpx.AsyncClient) -> str:
    response = await client.post("/api/v1/chat/threads")
    assert response.status_code == 201
    thread_id: str = response.json()["id"]
    return thread_id


def events_of(response: httpx.Response) -> list[dict[str, Any]]:
    """The JSON data of every event in a server-sent event stream."""
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


async def send(client: httpx.AsyncClient, thread_id: str, text: str) -> httpx.Response:
    return await client.post(
        f"/api/v1/chat/threads/{thread_id}/messages", json={"text": text}
    )


async def test_creating_a_thread_needs_a_signed_in_device(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/api/v1/chat/threads", headers={"Authorization": ""})

    assert response.status_code == 401


async def test_add_a_task_to_buy_milk(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """Stage 2 over HTTP; streamed replies 1: the reply comes as server-sent events."""
    thread_id = await new_thread(client)

    response = await send(client, thread_id, ADD_MILK)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = events_of(response)
    [entry] = await session.scalars(select(AuditEntry))
    assert events[:-1] == [
        {
            "type": "tool_call",
            "name": "create_task",
            "summary": "Creating a task: Buy milk",
            "ok": True,
            # Decision #119.
            "status": "done",
            "entry_id": str(entry.id),
            "domain": "tasks",
            "action_class": "write-internal",
        },
        {"type": "text", "text": "Added "},
        {"type": "text", "text": "it."},
    ]
    assert events[-1]["type"] == "done"
    [task] = await session.scalars(select(Task))
    assert task.title == "Buy milk"
    thread = await chat.get_thread(session, task.user_id, uuid.UUID(thread_id))
    [_, reply] = await chat.history(session, thread)
    assert str(reply.id) == events[-1]["message_id"]


async def test_another_users_thread_answers_404_and_claude_is_not_asked(
    client: httpx.AsyncClient, session: AsyncSession, claude: Claude
) -> None:
    """Threads 1."""
    other = User(username="other", password_hash="$argon2id$v=19$placeholder")
    session.add(other)
    await session.flush()
    thread = await chat.create_thread(session, other.id)

    response = await send(client, str(thread.id), ADD_MILK)

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert claude.asked == 0


@pytest.mark.parametrize("text", ["", "x" * (chat_api.DEFAULT_MAX_MESSAGE_LENGTH + 1)])
async def test_an_empty_or_huge_message_is_refused(
    client: httpx.AsyncClient, claude: Claude, text: str
) -> None:
    thread_id = await new_thread(client)

    response = await send(client, thread_id, text)

    assert response.status_code == 422
    assert claude.asked == 0


async def test_the_node_sets_the_longest_message(
    client: httpx.AsyncClient, claude: Claude, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TITAN_DEFAULT_MAX_MESSAGE_LENGTH", "10")
    thread_id = await new_thread(client)

    too_long = await send(client, thread_id, "x" * 11)
    fits = await send(client, thread_id, "x" * 10)

    assert too_long.status_code == 422
    assert too_long.json()["errors"] == [
        {"field": "body.text", "message": "Value error, longer than 10 characters"}
    ]
    assert fits.status_code == 200
    assert claude.asked == 1


@pytest.mark.parametrize("claude", [Claude(fail=True)])
async def test_a_failed_turn_keeps_nothing_and_says_so(
    client: httpx.AsyncClient,
    session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Decision: a turn that fails is rolled back whole."""
    thread_id = await new_thread(client)

    with caplog.at_level(logging.ERROR):
        response = await send(client, thread_id, ADD_MILK)

    assert events_of(response)[-1] == {"type": "error", "title": chat_api.FAILED.title}
    assert list(await session.scalars(select(Task))) == []
    assert list(await session.scalars(select(ChatMessage))) == []
    assert "TurnFailedError" in caplog.text
    assert "milk" not in caplog.text


async def test_a_client_that_leaves_loses_nothing(
    client: httpx.AsyncClient, session: AsyncSession, claude: Claude
) -> None:
    """Streamed replies 4 (decision #36): the turn runs to the end and is stored."""
    user = await session.scalar(select(User).where(User.username == "owner"))
    assert user is not None
    thread = await chat.create_thread(session, user.id)
    sessions = async_sessionmaker(
        bind=session.bind, join_transaction_mode="create_savepoint"
    )
    ask: Ask = claude
    stream = chat_api.send_message(
        thread, chat_api.MessageIn(text=ADD_MILK), sessions, ask
    )

    await anext(stream)
    await stream.aclose()
    await asyncio.gather(*chat_api.running)

    [question, reply] = await chat.history(session, thread)
    assert (question.text, reply.text) == (ADD_MILK, "Added it.")
