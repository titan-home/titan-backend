"""titan chat: a message in a new thread, the reply printed as it streams."""

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import assert_never

import httpx

from titan_cli.account import TOKEN_REJECTED, signed_in
from titan_cli.client.api.default import create_thread
from titan_cli.client.models import (
    ChatDoneEvent,
    ChatErrorEvent,
    ChatTextEvent,
    ChatToolCallEvent,
    ChatToolCallEventStatus,
    MessageIn,
    Mode,
    Problem,
    ThreadOut,
)
from titan_cli.node import CliError, api_client


@dataclass(frozen=True)
class NewerToolCall:
    """A tool call with a status, domain or class this CLI does not know yet.

    A newer node may add values (development rules, section 9); the call is
    still shown, with its status as the node sent it.
    """

    name: str
    summary: str
    status: str


# The events as the contract describes them.
NodeEvent = ChatTextEvent | ChatToolCallEvent | ChatDoneEvent | ChatErrorEvent
ChatEvent = NodeEvent | NewerToolCall

# The node pings a quiet stream every 15 seconds, so a minute of silence
# means the connection is gone.
STREAM_TIMEOUT = httpx.Timeout(10.0, read=60.0)

DATA_PREFIX = "data:"
EVENT_CLASSES: dict[str, type[NodeEvent]] = {
    "done": ChatDoneEvent,
    "error": ChatErrorEvent,
    "text": ChatTextEvent,
    "tool_call": ChatToolCallEvent,
}


def chat(text: str) -> None:
    """Send text in a new thread (decision #107) and print the reply."""
    saved = signed_in()
    client = api_client(saved.url, saved.token)

    thread = create_thread.sync(client=client)
    if not isinstance(thread, ThreadOut):
        if isinstance(thread, Problem) and thread.status == 401:
            raise CliError(TOKEN_REJECTED)
        raise CliError("the node refused to start a thread")

    # The generated send_message reads the whole answer before it returns,
    # so the stream is read with the client's own httpx client.
    with client.get_httpx_client().stream(
        "POST",
        f"/api/v1/chat/threads/{thread.id}/messages",
        json=MessageIn(text=text).to_dict(),
        timeout=STREAM_TIMEOUT,
    ) as response:
        if response.status_code != 200:
            response.read()
            raise _refused(response)
        try:
            print_reply(read_events(response.iter_lines()))
        except KeyboardInterrupt:
            # Only this client stops; the turn runs to the end (decision #36).
            print()
            raise CliError("stopped; the node still finishes the reply") from None


def _refused(response: httpx.Response) -> CliError:
    """Why the node did not take the message, for whoever runs titan."""
    if response.status_code == 401:
        return CliError(TOKEN_REJECTED)
    if response.headers.get("Content-Type") != "application/problem+json":
        return CliError(f"the node answered {response.status_code}.")
    problem = Problem.from_dict(response.json())
    reasons = [error.message for error in problem.errors or []]
    return CliError(
        f"the node refused the message: {'; '.join(reasons) or problem.title}"
    )


def read_events(lines: Iterable[str]) -> Iterator[ChatEvent]:
    """The events of a reply stream, from its lines (decision #104).

    Every event is one `data:` line holding a JSON object whose `type` says
    which event it is. Comment lines, such as the node's `: ping`, and the
    blank lines between events carry nothing. An event type this CLI does not
    know is skipped: a newer node may add one (development rules, section 9).
    A stream whose connection breaks simply ends.
    """
    try:
        for line in lines:
            if not line.startswith(DATA_PREFIX):
                continue
            event = _parse_event(line.removeprefix(DATA_PREFIX))
            if event is not None:
                yield event
    except httpx.TransportError:
        # print_reply sees a stream that ended without done and says so.
        return


def _parse_event(data: str) -> ChatEvent | None:
    """The event in a data line; None for a type this CLI does not know."""
    try:
        fields = json.loads(data)
        event_class = EVENT_CLASSES.get(fields["type"])
        if event_class is None:
            return None
        try:
            return event_class.from_dict(fields)
        except ValueError:
            # The generated enums refuse a value they do not know.
            if event_class is not ChatToolCallEvent:
                raise
            return NewerToolCall(
                str(fields["name"]), str(fields["summary"]), str(fields["status"])
            )
    except (KeyError, TypeError, ValueError):
        raise CliError("the node sent an event titan cannot read") from None


def _status(call: ChatToolCallEvent) -> str:
    """How a tool call's line ends, by its status."""
    match call.status:
        # The Undo of decision #37, in the terminal (decision #139).
        case ChatToolCallEventStatus.DONE if call.mode == Mode.AUTO_UNDO:
            return f"✓ undo: titan undo {call.entry_id}"
        case ChatToolCallEventStatus.DONE:
            return "✓"
        case ChatToolCallEventStatus.FAILED:
            return "✗"
        case ChatToolCallEventStatus.PENDING:
            return f"⏳ waiting for approval: titan approve {call.entry_id}"
        case ChatToolCallEventStatus.DENIED:
            return "⊘ not allowed"
        case _:
            assert_never(call.status)


def print_reply(events: Iterable[ChatEvent]) -> None:
    """Print the reply as it streams; CliError if it fails or breaks off.

    Text is printed as it comes, without waiting for a whole line. Each tool
    call gets a line of its own, `· name: summary` and its status: `✓` done,
    `✓ undo: titan undo <entry id>` done in auto-undo (decision #139), `✗`
    failed, `⏳ waiting for approval: titan approve <entry id>` pending,
    `⊘ not allowed` denied (decision #119); a status this CLI does not know
    is printed as the node sent it. `done` ends the reply with a newline.
    `error` ends it with CliError and the event's title. A stream that ends
    with neither was cut off: CliError says so, and that the node still
    finishes and keeps the reply (decision #36).
    """
    is_line_open = False
    for event in events:
        if is_line_open and not isinstance(event, ChatTextEvent):
            print()
            is_line_open = False
        match event:
            case ChatTextEvent():
                print(event.text, end="", flush=True)
                if event.text:
                    is_line_open = not event.text.endswith("\n")
            case ChatToolCallEvent():
                print(f"· {event.name}: {event.summary} {_status(event)}")
            case NewerToolCall():
                print(f"· {event.name}: {event.summary} {event.status}")
            case ChatDoneEvent():
                return
            case ChatErrorEvent():
                raise CliError(event.title)
            case _:
                assert_never(event)
    if is_line_open:
        print()
    raise CliError(
        "the connection was lost before the reply ended;"
        " the node still finishes it, so do not send the message again"
    )
