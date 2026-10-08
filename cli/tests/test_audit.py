"""Tests for titan undo (decisions #135, #136)."""

import functools
import json
import uuid
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from titan_cli.account import TOKEN_REJECTED
from titan_cli.main import main

NODE = "https://titan.example.ts.net"
TOKEN = "titan_v1_" + "t" * 43
ENTRIES = f"{NODE}/api/v1/audit/entries"
ENTRY_ID = uuid.UUID("5d0c7a3e-0000-4000-8000-000000000001")

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def login_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """This device is signed in to NODE."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = tmp_path / "titan" / "login.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"url": NODE, "token": TOKEN}))
    return path


def serve(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> list[httpx.Request]:
    """Answer the CLI's requests with handler; return the requests it sent."""
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    transport = httpx.MockTransport(record)
    monkeypatch.setattr(
        httpx, "Client", functools.partial(httpx.Client, transport=transport)
    )
    return requests


def problem(status: int, title: str, detail: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"type": "about:blank", "title": title, "status": status}
    if detail:
        body["detail"] = detail
    return httpx.Response(
        status, json=body, headers={"Content-Type": "application/problem+json"}
    )


def undo_entry() -> dict[str, object]:
    """The undo's entry as the node sends it."""
    return {
        "id": "5d0c7a3e-0000-4000-8000-000000000002",
        "tool": "undo",
        "summary": "Undo: Creating a task: Buy milk",
        "domain": "tasks",
        "action_class": "write-internal",
        "mode": None,
        "status": "done",
        "undoable": True,
        "undoes_entry_id": str(ENTRY_ID),
        "created_at": "2026-10-08T12:00:00.123456+00:00",
    }


def exit_message(arguments: list[str]) -> object:
    with pytest.raises(SystemExit) as exit_info:
        main(arguments)
    return exit_info.value.code


def test_undo_prints_the_undo(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Decision #136: an action is undone from the terminal by its full id."""
    requests = serve(
        monkeypatch, lambda request: httpx.Response(200, json=undo_entry())
    )

    main(["undo", str(ENTRY_ID)])

    [request] = requests
    assert (request.method, str(request.url)) == ("POST", f"{ENTRIES}/{ENTRY_ID}/undo")
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert capsys.readouterr().out == "Undo: Creating a task: Buy milk — done.\n"


def test_a_refused_undo_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decision #135: every refusal is 409 with a plain detail."""
    reason = "Cannot undo: something this action changed was changed later."
    serve(monkeypatch, lambda request: problem(409, "Conflict", reason))

    assert exit_message(["undo", str(ENTRY_ID)]) == f"titan: {reason}"


def test_an_action_the_node_does_not_have_is_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit log 3: another user's action is not found either."""
    serve(monkeypatch, lambda request: problem(404, "Not Found"))

    assert exit_message(["undo", str(ENTRY_ID)]) == (
        f"titan: there is no action {ENTRY_ID} in your log"
    )


def test_a_token_that_no_longer_works_says_how_to_sign_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serve(monkeypatch, lambda request: problem(401, "Unauthorized"))

    assert exit_message(["undo", str(ENTRY_ID)]) == f"titan: {TOKEN_REJECTED}"


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"id": "no summary"}),
        httpx.Response(200, json=["not", "an", "entry"]),
    ],
)
def test_an_answer_that_cannot_be_read_may_have_undone_it(
    monkeypatch: pytest.MonkeyPatch, answer: httpx.Response
) -> None:
    requests = serve(monkeypatch, lambda request: answer)

    assert exit_message(["undo", str(ENTRY_ID)]) == (
        "titan: the node's answer could not be read; the action may have been undone"
    )
    # Not sent again.
    assert len(requests) == 1


def test_an_id_that_is_not_a_uuid_is_not_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = serve(monkeypatch, lambda request: httpx.Response(200))

    with pytest.raises(SystemExit) as exit_info:
        main(["undo", "abc"])

    assert exit_info.value.code == 2
    assert requests == []
