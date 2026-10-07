"""Tests for titan chat (clients.md: CLI 2; decision #107)."""

import functools
import json
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from titan_cli.chat import ChatEvent, print_reply, read_events
from titan_cli.client.models import (
    ChatDoneEvent,
    ChatErrorEvent,
    ChatTextEvent,
    ChatToolCallEvent,
)
from titan_cli.main import main
from titan_cli.node import CliError

NODE = "https://titan.example.ts.net"
TOKEN = "titan_v1_" + "t" * 43
THREAD_ID = uuid.UUID("5d0c7a3e-0000-4000-8000-000000000001")
REPLY_ID = uuid.UUID("5d0c7a3e-0000-4000-8000-000000000002")
UNAUTHORIZED = {"type": "about:blank", "title": "Unauthorized", "status": 401}

CALL = ChatToolCallEvent(name="create_task", summary="Buy milk", ok=True)
DONE = ChatDoneEvent(message_id=REPLY_ID)
DONE_LINE = f'data: {{"type": "done", "message_id": "{REPLY_ID}"}}'


@pytest.fixture(autouse=True)
def login_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """This device is signed in to NODE."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = tmp_path / "titan" / "login.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"url": NODE, "token": TOKEN}))
    return path


def reply(*events: dict[str, object]) -> httpx.Response:
    """A reply stream as the node sends it, a keep-alive ping first."""
    lines = [": ping", ""]
    for event in events:
        lines += [f"data: {json.dumps(event)}", ""]
    return httpx.Response(
        200,
        content="\n".join(lines).encode(),
        headers={"Content-Type": "text/event-stream"},
    )


def node(
    monkeypatch: pytest.MonkeyPatch,
    messages: httpx.Response,
    threads: httpx.Response | None = None,
) -> list[httpx.Request]:
    """A node that starts a thread and answers its message; the requests sent."""
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v1/chat/threads":
            return threads or httpx.Response(201, json={"id": str(THREAD_ID)})
        return messages

    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(
        httpx, "Client", functools.partial(httpx.Client, transport=transport)
    )
    return requests


# read_events


@pytest.mark.parametrize(
    ("line", "event"),
    [
        ('data: {"type": "text", "text": "On it."}', ChatTextEvent(text="On it.")),
        (
            'data: {"type": "tool_call", "name": "create_task",'
            ' "summary": "Buy milk", "ok": true}',
            CALL,
        ),
        (DONE_LINE, DONE),
        (
            'data: {"type": "error", "title": "Send the message again"}',
            ChatErrorEvent(title="Send the message again"),
        ),
    ],
)
def test_each_data_line_is_one_event(line: str, event: object) -> None:
    """Decision #104."""
    assert list(read_events([line, ""])) == [event]


def test_pings_and_blank_lines_carry_nothing() -> None:
    assert list(read_events([": ping", "", "", DONE_LINE, ""])) == [DONE]


def test_an_event_this_cli_does_not_know_is_skipped() -> None:
    lines = ['data: {"type": "approval", "id": "x"}', "", DONE_LINE, ""]

    assert list(read_events(lines)) == [DONE]


@pytest.mark.parametrize(
    "line",
    [
        "data: not json",
        "data: []",
        'data: {"text": "no type"}',
        'data: {"type": "tool_call", "name": "create_task"}',
    ],
)
def test_a_damaged_event_stops_with_an_error(line: str) -> None:
    with pytest.raises(CliError):
        list(read_events([line, ""]))


def broken_off() -> Iterator[str]:
    """The lines of a stream whose connection drops after the first event."""
    yield 'data: {"type": "text", "text": "Adding"}'
    yield ""
    raise httpx.RemoteProtocolError("peer closed connection")


def test_a_stream_that_breaks_off_just_ends() -> None:
    assert list(read_events(broken_off())) == [ChatTextEvent(text="Adding")]


# print_reply


def test_the_text_is_printed_as_it_comes_and_ends_with_a_newline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    print_reply([ChatTextEvent(text="Added "), ChatTextEvent(text="it."), DONE])

    assert capsys.readouterr().out == "Added it.\n"


def test_a_tool_call_gets_a_line_of_its_own(
    capsys: pytest.CaptureFixture[str],
) -> None:
    print_reply(
        [ChatTextEvent(text="On it."), CALL, ChatTextEvent(text="Added."), DONE]
    )

    assert capsys.readouterr().out == "On it.\n· create_task: Buy milk ✓\nAdded.\n"


def test_a_tool_call_before_any_text_starts_the_reply(
    capsys: pytest.CaptureFixture[str],
) -> None:
    print_reply([CALL, ChatTextEvent(text="Added."), DONE])

    assert capsys.readouterr().out == "· create_task: Buy milk ✓\nAdded.\n"


def test_a_failed_tool_call_is_marked(capsys: pytest.CaptureFixture[str]) -> None:
    failed = ChatToolCallEvent(name="create_task", summary="Buy milk", ok=False)

    print_reply([failed, ChatTextEvent(text="It did not work."), DONE])

    assert capsys.readouterr().out == "· create_task: Buy milk ✗\nIt did not work.\n"


def test_an_empty_piece_of_text_keeps_the_line_open(
    capsys: pytest.CaptureFixture[str],
) -> None:
    print_reply([ChatTextEvent(text="Adding"), ChatTextEvent(text=""), CALL, DONE])

    assert capsys.readouterr().out == "Adding\n· create_task: Buy milk ✓\n"


def test_an_error_ends_the_reply_with_its_title(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Decision #106: the turn failed and the user sends the message again."""
    events: list[ChatEvent] = [
        ChatTextEvent(text="Adding"),
        ChatErrorEvent(title="Send it again"),
    ]

    with pytest.raises(CliError, match="Send it again"):
        print_reply(events)

    assert capsys.readouterr().out == "Adding\n"


def test_a_stream_cut_off_says_the_node_keeps_the_reply(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Decision #36: the turn runs to the end on the node."""
    with pytest.raises(CliError, match="connection"):
        print_reply([ChatTextEvent(text="Adding")])

    assert capsys.readouterr().out == "Adding\n"


# titan chat


def test_chat_sends_the_message_in_a_new_thread_and_prints_the_reply(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Clients, CLI 2: the reply streams and shows tool activity."""
    requests = node(
        monkeypatch,
        reply(
            {"type": "text", "text": "On it."},
            {
                "type": "tool_call",
                "name": "create_task",
                "summary": "Buy milk",
                "ok": True,
            },
            {"type": "text", "text": "Added."},
            {"type": "done", "message_id": str(REPLY_ID)},
        ),
    )

    main(["chat", "add a task to buy milk"])

    create, send = requests
    assert (create.method, str(create.url)) == ("POST", f"{NODE}/api/v1/chat/threads")
    assert (send.method, str(send.url)) == (
        "POST",
        f"{NODE}/api/v1/chat/threads/{THREAD_ID}/messages",
    )
    assert json.loads(send.content) == {"text": "add a task to buy milk"}
    assert {request.headers["Authorization"] for request in requests} == {
        f"Bearer {TOKEN}"
    }
    assert capsys.readouterr().out == "On it.\n· create_task: Buy milk ✓\nAdded.\n"


def test_every_chat_starts_a_new_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decision #107."""
    requests = node(monkeypatch, reply({"type": "done", "message_id": str(REPLY_ID)}))

    main(["chat", "one"])
    main(["chat", "two"])

    created = [r for r in requests if r.url.path == "/api/v1/chat/threads"]
    assert len(created) == 2


def test_a_message_the_node_refuses_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decision #105: a message longer than the user's limit is refused."""
    too_long = {
        **{"type": "about:blank", "title": "Unprocessable Content", "status": 422},
        "errors": [{"field": "body.text", "message": "longer than 20000 characters"}],
    }
    node(
        monkeypatch,
        httpx.Response(
            422, json=too_long, headers={"Content-Type": "application/problem+json"}
        ),
    )

    with pytest.raises(SystemExit) as exit_info:
        main(["chat", "x"])

    assert "longer than 20000 characters" in str(exit_info.value.code)


def test_chat_with_a_token_that_no_longer_works_says_how_to_sign_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Device tokens 5: revoked or expired."""
    refused = httpx.Response(
        401, json=UNAUTHORIZED, headers={"Content-Type": "application/problem+json"}
    )
    requests = node(monkeypatch, reply(), threads=refused)

    with pytest.raises(SystemExit) as exit_info:
        main(["chat", "add a task to buy milk"])

    assert "titan login" in str(exit_info.value.code)
    assert len(requests) == 1


class BrokenOff(httpx.SyncByteStream):
    """A reply stream whose connection drops after the first event."""

    def __iter__(self) -> Iterator[bytes]:
        yield b'data: {"type": "text", "text": "Adding"}\n\n'
        raise httpx.RemoteProtocolError("peer closed connection")


def test_a_dropped_connection_says_not_to_send_the_message_again(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Decision #36: the turn runs to the end on the node."""
    node(monkeypatch, httpx.Response(200, stream=BrokenOff()))

    with pytest.raises(SystemExit) as exit_info:
        main(["chat", "add a task to buy milk"])

    assert "do not send the message again" in str(exit_info.value.code)
    assert capsys.readouterr().out == "Adding\n"


def test_ctrl_c_stops_only_this_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decision #36: the turn runs to the end on the node."""
    node(monkeypatch, reply({"type": "text", "text": "Adding"}))

    def interrupted(events: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("titan_cli.chat.print_reply", interrupted)

    with pytest.raises(SystemExit) as exit_info:
        main(["chat", "add a task to buy milk"])

    assert "node still finishes" in str(exit_info.value.code)


def test_chat_before_signing_in_says_how_to(
    monkeypatch: pytest.MonkeyPatch, login_file: Path
) -> None:
    login_file.unlink()
    requests = node(monkeypatch, reply())

    with pytest.raises(SystemExit) as exit_info:
        main(["chat", "add a task to buy milk"])

    assert "titan login" in str(exit_info.value.code)
    assert requests == []
