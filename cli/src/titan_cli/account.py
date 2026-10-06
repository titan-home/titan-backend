"""titan login and titan whoami: signing this device in and asking who it is."""

import json
import os
from dataclasses import asdict, dataclass
from getpass import getpass
from urllib.parse import urlsplit

from titan_cli.client.api.default import add_device
from titan_cli.client.api.default import whoami as whoami_api
from titan_cli.client.models import (
    DeviceRegistrationIn,
    DeviceRegistrationOut,
    Problem,
    WhoamiOut,
)
from titan_cli.node import CliError, api_client, login_path


@dataclass
class Login:
    """What login.json holds: the node signed in to and this device's token."""

    url: str
    token: str


def read_credentials() -> tuple[str, str]:
    """Ask for the username and, without echo, the password."""
    return input("Username: ").strip(), getpass("Password: ")


def _check_url(url: str, dev: bool) -> None:
    parsed_url = urlsplit(url)
    local = parsed_url.hostname in ("localhost", "127.0.0.1")
    allowed = parsed_url.scheme == "https" or (
        dev and local and parsed_url.scheme == "http"
    )
    if not allowed:
        raise CliError(
            "use https:// for a node; "
            + (
                "--dev allows plain http only to localhost and 127.0.0.1"
                if dev
                else "plain http is only for the development stack, with --dev"
            )
        )


def _read_login() -> Login | None:
    """The saved node address and token; None if this device is not signed in."""
    try:
        fd = os.open(login_path(), os.O_RDONLY)
        with os.fdopen(fd, encoding="utf-8") as f:
            return Login(**json.load(f))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        raise CliError(
            f"{login_path()} is damaged; run titan login URL again"
        ) from None


def _save_login(saved: Login) -> None:
    login_path().parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(login_path(), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(asdict(saved), f)


def login(url: str, name: str, dev: bool) -> None:
    """Sign this device in to the node at url and keep its token.

    Only https, unless dev allows plain http to this machine for the
    development stack (decision #94); signing in again sends
    the old token of the same node, so the device keeps its entry (#24).
    """

    _check_url(url, dev)

    saved = _read_login()
    old_token = None
    if saved is not None and saved.url == url:
        old_token = saved.token

    username, password = read_credentials()
    result = add_device.sync(
        client=api_client(url, old_token),
        body=DeviceRegistrationIn(username=username, password=password, name=name),
    )

    if not isinstance(result, DeviceRegistrationOut):
        if isinstance(result, Problem) and result.status == 401:
            raise CliError("wrong username or password")
        reason = result.title if isinstance(result, Problem) else "no answer"
        raise CliError(f"the node refused to sign in: {reason}")

    _save_login(Login(url=url, token=result.token))
    print(f"Signed in as {username} on {name}")


def whoami() -> None:
    """Print who is signed in on this device and the device's name."""
    saved = _read_login()
    if saved is None:
        raise CliError("not signed in on this device; run titan login URL first")

    result = whoami_api.sync(client=api_client(saved.url, saved.token))

    if not isinstance(result, WhoamiOut):
        if isinstance(result, Problem) and result.status == 401:
            raise CliError(
                "this device's token no longer works; run titan login URL again"
            )
        reason = result.title if isinstance(result, Problem) else "no answer"
        raise CliError(f"the node refused to tell who is signed in: {reason}")

    print(f"{result.username} on {result.device.name}")
