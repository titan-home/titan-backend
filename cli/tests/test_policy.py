"""Tests for titan policy (autonomy spec, defaults; decisions #115-#117)."""

import functools
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from titan_cli.main import main

NODE = "https://titan.example.ts.net"
TOKEN = "titan_v1_" + "t" * 43
MODES = f"{NODE}/api/v1/policy/modes"

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


def row(action_class: str, mode: str, own: bool) -> dict[str, object]:
    return {"domain": "tasks", "action_class": action_class, "mode": mode, "own": own}


def test_list_shows_every_mode_and_whose_it_is(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Defaults 1 and 2."""
    requests = serve(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json=[
                row("read", "auto", False),
                row("write-internal", "confirm", True),
            ],
        ),
    )

    main(["policy", "list"])

    [request] = requests
    assert (request.method, str(request.url)) == ("GET", MODES)
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert capsys.readouterr().out == (
        "tasks  read            auto       default\n"
        "tasks  write-internal  confirm    yours\n"
    )


def test_set_sends_the_mode_for_one_class_in_one_domain(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Defaults 2."""
    requests = serve(
        monkeypatch,
        lambda request: httpx.Response(
            200, json=row("write-internal", "confirm", True)
        ),
    )

    main(["policy", "set", "tasks", "write-internal", "confirm"])

    [request] = requests
    assert (request.method, str(request.url)) == (
        "PUT",
        f"{MODES}/tasks/write-internal",
    )
    assert json.loads(request.content) == {"mode": "confirm"}
    assert capsys.readouterr().out == "tasks write-internal: confirm\n"


def test_set_below_the_floor_shows_the_nodes_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defaults 5; decision #116."""
    serve(
        monkeypatch,
        lambda request: problem(
            422, "Unprocessable Content", "external can only be confirm or deny."
        ),
    )

    with pytest.raises(SystemExit) as exit_info:
        main(["policy", "set", "tasks", "external", "auto"])

    assert exit_info.value.code == "titan: external can only be confirm or deny."


def test_reset_returns_the_class_to_its_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    requests = serve(monkeypatch, lambda request: httpx.Response(204))

    main(["policy", "reset", "tasks", "write-internal"])

    [request] = requests
    assert (request.method, str(request.url)) == (
        "DELETE",
        f"{MODES}/tasks/write-internal",
    )
    assert capsys.readouterr().out == "tasks write-internal: back to the default\n"


@pytest.mark.parametrize(
    "arguments",
    [
        ["policy", "set", "finance", "write-internal", "confirm"],
        ["policy", "set", "tasks", "write", "confirm"],
        ["policy", "set", "tasks", "write-internal", "sometimes"],
    ],
)
def test_an_unknown_domain_class_or_mode_is_refused_before_asking_the_node(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    requests = serve(monkeypatch, lambda request: httpx.Response(500))

    with pytest.raises(SystemExit):
        main(arguments)

    assert requests == []


def test_a_token_that_no_longer_works_says_how_to_sign_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serve(monkeypatch, lambda request: problem(401, "Unauthorized"))

    with pytest.raises(SystemExit) as exit_info:
        main(["policy", "list"])

    assert "titan login" in str(exit_info.value.code)
