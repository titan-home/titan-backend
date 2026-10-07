"""Tests for titan approvals, approve and reject (clients.md: CLI 2; #118)."""

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
APPROVALS = f"{NODE}/api/v1/approvals"
FIRST_ID = uuid.UUID("5d0c7a3e-0000-4000-8000-000000000001")
SECOND_ID = uuid.UUID("5d0c7a3e-0000-4000-8000-000000000002")

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


def approval(
    approval_id: uuid.UUID = FIRST_ID,
    summary: object = "Delete the task Buy milk",
    status: str = "pending",
    domain: str = "tasks",
) -> dict[str, object]:
    """An approval request as the node sends it."""
    return {
        "id": str(approval_id),
        "tool": "delete_task",
        "summary": summary,
        "domain": domain,
        "action_class": "destructive",
        "status": status,
        "created_at": "2026-10-07T09:15:42.123456+00:00",
    }


# titan approvals


def test_approvals_lists_every_page_oldest_first(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Approvals 1: the summary, the domain and the class; decision #124."""

    def pages(request: httpx.Request) -> httpx.Response:
        if "after" not in request.url.params:
            return httpx.Response(200, json={"items": [approval()], "next": "c1"})
        return httpx.Response(
            200,
            json={
                "items": [approval(SECOND_ID, "Delete the note Plans")],
                "next": None,
            },
        )

    requests = serve(monkeypatch, pages)

    main(["approvals"])

    assert [(request.method, str(request.url)) for request in requests] == [
        ("GET", APPROVALS),
        ("GET", f"{APPROVALS}?after=c1"),
    ]
    assert requests[0].headers["Authorization"] == f"Bearer {TOKEN}"
    assert capsys.readouterr().out == (
        f"{FIRST_ID}  Delete the task Buy milk"
        "  tasks/destructive  2026-10-07 09:15+00:00\n"
        f"{SECOND_ID}  Delete the note Plans   "
        "  tasks/destructive  2026-10-07 09:15+00:00\n"
    )


def test_approvals_says_when_nothing_waits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    serve(
        monkeypatch,
        lambda request: httpx.Response(200, json={"items": [], "next": None}),
    )

    main(["approvals"])

    assert capsys.readouterr().out == "No approval requests are waiting.\n"


def test_approvals_shows_a_domain_this_cli_does_not_know(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A newer node may add values (development rules, section 9)."""
    serve(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={"items": [approval(domain="garden", status="held")], "next": None},
        ),
    )

    main(["approvals"])

    assert capsys.readouterr().out == (
        f"{FIRST_ID}  Delete the task Buy milk"
        "  garden/destructive  2026-10-07 09:15+00:00\n"
    )


# titan approve and titan reject


def test_approve_prints_the_outcome(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Approvals 2: decided from the CLI."""
    requests = serve(
        monkeypatch, lambda request: httpx.Response(200, json=approval(status="done"))
    )

    main(["approve", str(FIRST_ID)])

    [request] = requests
    assert (request.method, str(request.url)) == (
        "POST",
        f"{APPROVALS}/{FIRST_ID}/approve",
    )
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert capsys.readouterr().out == "Approved: Delete the task Buy milk — done.\n"


def test_an_approved_call_that_failed_is_an_outcome_not_an_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The request was decided; like a failed call in titan chat, it exits 0."""
    serve(
        monkeypatch, lambda request: httpx.Response(200, json=approval(status="failed"))
    )

    main(["approve", str(FIRST_ID)])

    assert capsys.readouterr().out == "Approved: Delete the task Buy milk — failed.\n"


def test_approve_shows_a_status_this_cli_does_not_know(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A newer node may add values (development rules, section 9)."""
    serve(
        monkeypatch,
        lambda request: httpx.Response(
            200, json=approval(status="queued", domain="garden")
        ),
    )

    main(["approve", str(FIRST_ID)])

    assert capsys.readouterr().out == "Approved: Delete the task Buy milk — queued.\n"


def test_reject_says_what_was_rejected(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    requests = serve(
        monkeypatch,
        lambda request: httpx.Response(200, json=approval(status="rejected")),
    )

    main(["reject", str(FIRST_ID)])

    [request] = requests
    assert (request.method, str(request.url)) == (
        "POST",
        f"{APPROVALS}/{FIRST_ID}/reject",
    )
    assert capsys.readouterr().out == "Rejected: Delete the task Buy milk.\n"


# Errors


@pytest.mark.parametrize(
    "arguments",
    [["approvals"], ["approve", str(FIRST_ID)], ["reject", str(FIRST_ID)]],
)
def test_a_token_that_no_longer_works_says_how_to_sign_in(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    serve(monkeypatch, lambda request: problem(401, "Unauthorized"))

    with pytest.raises(SystemExit) as exit_info:
        main(arguments)

    assert exit_info.value.code == f"titan: {TOKEN_REJECTED}"


@pytest.mark.parametrize("command", ["approve", "reject"])
def test_a_request_the_node_does_not_have_is_not_found(
    monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    """Approvals 4: another user's request is not found either."""
    serve(monkeypatch, lambda request: problem(404, "Not Found"))

    with pytest.raises(SystemExit) as exit_info:
        main([command, str(FIRST_ID)])

    assert exit_info.value.code == f"titan: there is no approval request {FIRST_ID}"


@pytest.mark.parametrize("command", ["approve", "reject"])
def test_a_request_decided_before_shows_the_nodes_reason(
    monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    """Approvals 3; decision #121."""
    serve(
        monkeypatch,
        lambda request: problem(
            409, "Conflict", "This request is already decided: done."
        ),
    )

    with pytest.raises(SystemExit) as exit_info:
        main([command, str(FIRST_ID)])

    assert exit_info.value.code == "titan: This request is already decided: done."


@pytest.mark.parametrize(
    "arguments",
    [["approvals"], ["approve", str(FIRST_ID)], ["reject", str(FIRST_ID)]],
)
def test_any_other_answer_is_a_short_error(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    serve(monkeypatch, lambda request: httpx.Response(500, text="oops"))

    with pytest.raises(SystemExit) as exit_info:
        main(arguments)

    assert exit_info.value.code == "titan: the node answered 500."


def test_an_answer_titan_cannot_read_is_a_short_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serve(monkeypatch, lambda request: httpx.Response(200, json={"items": [{}]}))

    with pytest.raises(SystemExit) as exit_info:
        main(["approvals"])

    assert exit_info.value.code == "titan: the node sent an answer titan cannot read"


@pytest.mark.parametrize("cursor", ["c1", ""])
def test_a_page_that_comes_back_again_stops_the_list(
    monkeypatch: pytest.MonkeyPatch, cursor: str
) -> None:
    """A node that sends the same next again would be asked for ever."""
    requests = serve(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"items": [approval()], "next": cursor}
        ),
    )

    with pytest.raises(SystemExit) as exit_info:
        main(["approvals"])

    assert exit_info.value.code == "titan: the node sent the same page twice"
    assert [request.url.params.get("after") for request in requests] == [None, cursor]


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(
            422, content=b"oops", headers={"Content-Type": "application/problem+json"}
        ),
        httpx.Response(
            422,
            json={"status": 422},
            headers={"Content-Type": "application/problem+json"},
        ),
    ],
)
def test_a_problem_titan_cannot_read_is_a_short_error(
    monkeypatch: pytest.MonkeyPatch, answer: httpx.Response
) -> None:
    serve(monkeypatch, lambda request: answer)

    with pytest.raises(SystemExit) as exit_info:
        main(["approve", str(FIRST_ID)])

    assert exit_info.value.code == "titan: the node answered 422."


def test_a_summary_that_is_not_text_is_shown_as_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    serve(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "items": [approval(summary=None), approval(SECOND_ID, 42, domain="x")],
                "next": None,
            },
        ),
    )

    main(["approvals"])

    assert capsys.readouterr().out == (
        f"{FIRST_ID}  None  tasks/destructive  2026-10-07 09:15+00:00\n"
        f"{SECOND_ID}  42    x/destructive  2026-10-07 09:15+00:00\n"
    )


@pytest.mark.parametrize("command", ["approve", "reject"])
@pytest.mark.parametrize(
    "answer",
    [httpx.Response(200, text="oops"), httpx.Response(200, json={"summary": "x"})],
)
def test_a_decision_whose_answer_cannot_be_read_may_have_been_made(
    monkeypatch: pytest.MonkeyPatch, command: str, answer: httpx.Response
) -> None:
    """The call may have run, so the user is sent to look rather than retry."""
    serve(monkeypatch, lambda request: answer)

    with pytest.raises(SystemExit) as exit_info:
        main([command, str(FIRST_ID)])

    assert exit_info.value.code == (
        "titan: the node's answer could not be read; the request may have been"
        " decided, run titan approvals"
    )
