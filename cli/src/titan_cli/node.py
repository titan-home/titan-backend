"""The node this CLI talks to: where its login is kept and the API client."""

import os
from pathlib import Path
from typing import cast

from titan_cli.client import AuthenticatedClient, Client


class CliError(Exception):
    """A problem to show to whoever runs titan, without a traceback."""


def login_path() -> Path:
    """The file with the node's address and this device's token (decision #89)."""
    config = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(config) / "titan" / "login.json"


def api_client(url: str, token: str | None = None) -> AuthenticatedClient:
    """A client of the node's API that sends this device's token, if any."""
    if token is None:
        # The contract makes the token optional for signing in, but the
        # generated functions ask for an AuthenticatedClient regardless; a
        # plain Client does the same without an Authorization header.
        return cast(AuthenticatedClient, Client(url, raise_on_unexpected_status=True))
    return AuthenticatedClient(url, token=token, raise_on_unexpected_status=True)
