"""Chat: threads, and messages answered by the agent as a stream of events."""

import asyncio
import logging
import os
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.sse import EventSourceResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from titan_server.agent.claude import ask_claude
from titan_server.agent.turn import Ask, ReplyStored, TextDelta, ToolCalled, run_turn
from titan_server.api.dependencies import BackgroundSessions, CurrentDevice, Session
from titan_server.api.problems import problems
from titan_server.domains.chat import service as chat
from titan_server.domains.chat.models import Thread

logger = logging.getLogger(__name__)

# Long enough for a pasted page or two; a message is sent to Claude whole.
DEFAULT_MAX_MESSAGE_LENGTH = 20_000


def max_message_length() -> int:
    """The longest message a user may send; see TITAN_DEFAULT_MAX_MESSAGE_LENGTH.

    NOTE: every user gets the node's default until users have settings; then
    a user's own limit comes first.
    """
    return int(
        os.environ.get("TITAN_DEFAULT_MAX_MESSAGE_LENGTH", DEFAULT_MAX_MESSAGE_LENGTH)
    )


class ThreadOut(BaseModel):
    """A new thread."""

    id: uuid.UUID


class MessageIn(BaseModel):
    """What the user wrote."""

    # The limit is the node's setting, so the contract names only the default
    # (as for page sizes, decision #83).
    text: str = Field(
        min_length=1,
        description=(
            "At most as many characters as the user's limit allows,"
            f" {DEFAULT_MAX_MESSAGE_LENGTH} by default."
        ),
    )

    @field_validator("text")
    @classmethod
    def within_the_nodes_limit(cls, text: str) -> str:
        """Refuse a message longer than the node's limit."""
        if len(text) > max_message_length():
            raise ValueError(f"longer than {max_message_length()} characters")
        return text


class ChatEventBase(BaseModel):
    """An event of the reply stream; `type` is always sent, so it is required."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class ChatTextEvent(ChatEventBase):
    """The next piece of the reply's text, as Claude writes it."""

    type: Literal["text"] = "text"
    text: str


class ChatToolCallEvent(ChatEventBase):
    """A tool call that ran: its name, a line a person can read, its outcome."""

    type: Literal["tool_call"] = "tool_call"
    name: str
    summary: str
    ok: bool


class ChatDoneEvent(ChatEventBase):
    """The reply is complete and stored; the stream ends."""

    type: Literal["done"] = "done"
    message_id: uuid.UUID


class ChatErrorEvent(ChatEventBase):
    """The turn failed and nothing of it was kept; the stream ends."""

    type: Literal["error"] = "error"
    title: str


ChatEvent = Annotated[
    ChatTextEvent | ChatToolCallEvent | ChatDoneEvent | ChatErrorEvent,
    Field(discriminator="type"),
]

FAILED = ChatErrorEvent(title="The reply could not be finished; send the message again")


def claude() -> Ask:
    """Who answers a turn: Claude, or a script in the tests."""
    return ask_claude


async def own_thread(
    thread_id: uuid.UUID, device: CurrentDevice, session: Session
) -> Thread:
    """The signed-in user's thread from the path; 404 for any other."""
    try:
        return await chat.get_thread(session, device.user_id, thread_id)
    except chat.ThreadNotFoundError:
        raise HTTPException(404) from None


# Turns that are running; a reference keeps each one alive after its client
# has gone (decision #36).
# NOTE: a turn running when the api stops is lost with its message; keep
# turns in the database and resume them if that happens too often.
running: set[asyncio.Task[None]] = set()


async def turn(
    sessions: async_sessionmaker[AsyncSession],
    thread: Thread,
    text: str,
    ask: Ask,
    events: asyncio.Queue[ChatEvent | None],
) -> None:
    """Run a turn in a transaction of its own and put its events on the queue.

    A turn that fails is rolled back whole: the message, what its tools did
    and the reply.
    """
    done: ChatEvent = FAILED
    reply: ChatEvent = FAILED
    try:
        async with sessions() as session, session.begin():
            turn_events = run_turn(
                session, thread.user_id, thread.id, text, datetime.now(UTC), ask
            )
            async for event in turn_events:
                if isinstance(event, TextDelta):
                    events.put_nowait(ChatTextEvent(text=event.text))
                elif isinstance(event, ToolCalled):
                    events.put_nowait(ChatToolCallEvent(**event.call))
                elif isinstance(event, ReplyStored):
                    reply = ChatDoneEvent(message_id=event.reply_id)
        # Told only once the reply is committed.
        done = reply
    except Exception as error:
        # The type only: an error's text may quote the conversation.
        logger.error("A chat turn failed: %s", type(error).__name__)
    finally:
        events.put_nowait(done)
        events.put_nowait(None)


router = APIRouter(prefix="/chat")


@router.post("/threads", status_code=201, responses=problems(401))
async def create_thread(device: CurrentDevice, session: Session) -> ThreadOut:
    """Start a new, empty thread."""
    thread = await chat.create_thread(session, device.user_id)
    return ThreadOut(id=thread.id)


@router.post(
    "/threads/{thread_id}/messages",
    response_class=EventSourceResponse,
    responses=problems(401, 404),
)
async def send_message(
    thread: Annotated[Thread, Depends(own_thread)],
    message: MessageIn,
    sessions: BackgroundSessions,
    ask: Annotated[Ask, Depends(claude)],
) -> AsyncGenerator[ChatEvent]:
    """Send a message and get the agent's reply as server-sent events.

    Every event's data is one JSON object whose `type` says what it is. The
    stream ends with `done` or `error`. A client that disconnects loses
    nothing: the turn runs to the end and its reply is stored.
    """
    events: asyncio.Queue[ChatEvent | None] = asyncio.Queue()
    task = asyncio.create_task(turn(sessions, thread, message.text, ask, events))
    running.add(task)
    task.add_done_callback(running.discard)
    while (event := await events.get()) is not None:
        yield event
