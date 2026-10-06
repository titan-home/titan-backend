"""Tests for titan login and titan whoami (accounts.md: sign in, device tokens)."""

import contextlib
import functools
import json
import stat
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from titan_cli import account
from titan_cli.main import main

NODE = "https://titan.example.ts.net"
PASSWORD = "correct horse"
OLD_TOKEN = "titan_v1_" + "o" * 43
NEW_TOKEN = "titan_v1_" + "n" * 43
UNAUTHORIZED = {"type": "about:blank", "title": "Unauthorized", "status": 401}

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(account, "read_credentials", lambda: ("owner", PASSWORD))
    return tmp_path


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


def paired(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        201,
        json={
            "id": "8f1c2a4e-0000-4000-8000-000000000000",
            "name": "laptop",
            "token": NEW_TOKEN,
        },
    )


def refused(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        401, json=UNAUTHORIZED, headers={"Content-Type": "application/problem+json"}
    )


def login_file(config_home: Path) -> Path:
    return config_home / "titan" / "login.json"


def save_login(config_home: Path, url: str, token: str) -> None:
    path = login_file(config_home)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"url": url, "token": token}))


def bearer(request: httpx.Request) -> str:
    """The bearer token a request carried, or "" without one."""
    header: str = request.headers.get("Authorization", "")
    return header.removeprefix("Bearer").strip()


def test_login_pairs_this_device_and_keeps_its_token_privately(
    monkeypatch: pytest.MonkeyPatch, config_home: Path
) -> None:
    """Sign in 1, device tokens 1."""
    requests = serve(monkeypatch, paired)

    main(["login", NODE, "--name", "laptop"])

    [request] = requests
    assert (request.method, str(request.url)) == ("POST", f"{NODE}/api/v1/devices")
    assert json.loads(request.content) == {
        "username": "owner",
        "password": PASSWORD,
        "name": "laptop",
    }
    assert "Authorization" not in request.headers
    path = login_file(config_home)
    assert json.loads(path.read_text()) == {"url": NODE, "token": NEW_TOKEN}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_the_device_is_named_after_the_host_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("socket.gethostname", lambda: "workstation")
    requests = serve(monkeypatch, paired)

    main(["login", NODE])

    assert json.loads(requests[0].content)["name"] == "workstation"


def test_signing_in_again_sends_the_old_token(
    monkeypatch: pytest.MonkeyPatch, config_home: Path
) -> None:
    """Device tokens 2: the node replaces the token and keeps the device."""
    save_login(config_home, NODE, OLD_TOKEN)
    requests = serve(monkeypatch, paired)

    main(["login", NODE, "--name", "laptop"])

    assert bearer(requests[0]) == OLD_TOKEN
    assert json.loads(login_file(config_home).read_text())["token"] == NEW_TOKEN


def test_a_token_of_another_node_is_never_sent(
    monkeypatch: pytest.MonkeyPatch, config_home: Path
) -> None:
    save_login(config_home, "https://other.example.ts.net", OLD_TOKEN)
    requests = serve(monkeypatch, paired)

    main(["login", NODE, "--name", "laptop"])

    assert "Authorization" not in requests[0].headers


def test_a_wrong_password_saves_nothing(
    monkeypatch: pytest.MonkeyPatch, config_home: Path
) -> None:
    """Sign in 2."""
    serve(monkeypatch, refused)

    with pytest.raises(SystemExit) as exit_info:
        main(["login", NODE, "--name", "laptop"])

    assert "username or password" in str(exit_info.value.code)
    assert not login_file(config_home).exists()


def test_any_other_refusal_is_reported_and_saves_nothing(
    monkeypatch: pytest.MonkeyPatch, config_home: Path
) -> None:
    invalid = {"type": "about:blank", "title": "Unprocessable Content", "status": 422}
    serve(monkeypatch, lambda request: httpx.Response(422, json=invalid))

    with pytest.raises(SystemExit) as exit_info:
        main(["login", NODE, "--name", "laptop"])

    assert exit_info.value.code != 0
    assert not login_file(config_home).exists()


@pytest.mark.parametrize("handler", [paired, refused])
def test_the_password_is_never_printed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    handler: Handler,
) -> None:
    """Sign in 4."""
    serve(monkeypatch, handler)

    with contextlib.suppress(SystemExit):
        main(["login", NODE, "--name", "laptop"])

    printed = capsys.readouterr()
    assert PASSWORD not in printed.out + printed.err
    assert NEW_TOKEN not in printed.out + printed.err


@pytest.mark.parametrize(
    "arguments",
    [
        ["http://titan.example.ts.net"],
        ["http://titan.example.ts.net", "--dev"],
        ["ftp://titan.example", "--dev"],
        ["http://127.0.0.1:8000"],
        ["http://localhost:8000"],
    ],
)
def test_plain_http_is_refused_unless_dev_and_on_this_machine(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    """Decision #94: https for real nodes, plain http for the development stack."""
    requests = serve(monkeypatch, paired)

    with pytest.raises(SystemExit) as exit_info:
        main(["login", *arguments, "--name", "laptop"])

    assert "https" in str(exit_info.value.code)
    assert requests == []


@pytest.mark.parametrize("url", ["http://localhost:8000", "http://127.0.0.1:8000"])
def test_dev_allows_plain_http_to_this_machine(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    requests = serve(monkeypatch, paired)

    main(["login", "--dev", url, "--name", "laptop"])

    assert len(requests) == 1


def test_dev_still_signs_in_to_a_real_node_over_https(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = serve(monkeypatch, paired)

    main(["login", "--dev", NODE, "--name", "laptop"])

    assert len(requests) == 1


def test_whoami_shows_the_user_and_the_device(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    config_home: Path,
) -> None:
    """Sign in 5."""
    save_login(config_home, NODE, OLD_TOKEN)
    requests = serve(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"username": "owner", "device": {"name": "laptop"}}
        ),
    )

    main(["whoami"])

    [request] = requests
    assert (request.method, str(request.url)) == ("GET", f"{NODE}/api/v1/me")
    assert bearer(request) == OLD_TOKEN
    assert capsys.readouterr().out == "owner on laptop\n"


def test_whoami_before_signing_in_says_how_to(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = serve(monkeypatch, paired)

    with pytest.raises(SystemExit) as exit_info:
        main(["whoami"])

    assert "titan login" in str(exit_info.value.code)
    assert requests == []


def test_whoami_with_a_token_that_no_longer_works_says_how_to_sign_in(
    monkeypatch: pytest.MonkeyPatch, config_home: Path
) -> None:
    """Device tokens 5: revoked or expired."""
    save_login(config_home, NODE, OLD_TOKEN)
    serve(monkeypatch, refused)

    with pytest.raises(SystemExit) as exit_info:
        main(["whoami"])

    assert "titan login" in str(exit_info.value.code)


def test_a_damaged_login_file_says_how_to_sign_in_again(
    monkeypatch: pytest.MonkeyPatch, config_home: Path
) -> None:
    path = login_file(config_home)
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    requests = serve(monkeypatch, paired)

    with pytest.raises(SystemExit) as exit_info:
        main(["whoami"])

    assert "titan login" in str(exit_info.value.code)
    assert requests == []


def test_a_login_file_without_a_token_says_how_to_sign_in_again(
    monkeypatch: pytest.MonkeyPatch, config_home: Path
) -> None:
    path = login_file(config_home)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"url": NODE}))
    requests = serve(monkeypatch, paired)

    with pytest.raises(SystemExit) as exit_info:
        main(["whoami"])

    assert "titan login" in str(exit_info.value.code)
    assert requests == []
