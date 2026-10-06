"""Entry point of the titan command."""

import argparse
import socket
import sys
from importlib.metadata import version

import httpx

from titan_cli.account import login, whoami
from titan_cli.client.errors import UnexpectedStatus
from titan_cli.node import CliError


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and run the command it names."""
    parser = argparse.ArgumentParser(
        prog="titan", description="TITAN from the command line."
    )
    parser.add_argument("--version", action="version", version=version("titan-cli"))
    commands = parser.add_subparsers(dest="command", required=True)
    # No username or password options on purpose: they would end up in the
    # shell history and the process list.
    login_parser = commands.add_parser("login", help="sign this device in to a node")
    login_parser.add_argument(
        "url", help="the node's address, such as https://titan.example.ts.net"
    )
    login_parser.add_argument(
        "--name",
        default=socket.gethostname(),
        help="this device's name on the node; the host name by default",
    )
    login_parser.add_argument(
        "--dev",
        action="store_true",
        help="allow plain http to localhost, for the development stack",
    )
    commands.add_parser("whoami", help="show who is signed in on this device")
    arguments = parser.parse_args(argv)

    try:
        if arguments.command == "login":
            login(arguments.url, arguments.name, arguments.dev)
        else:
            whoami()
    except CliError as error:
        sys.exit(f"titan: {error}")
    except httpx.TransportError as error:
        sys.exit(f"titan: cannot reach the node: {error}")
    except UnexpectedStatus as error:
        sys.exit(f"titan: the node answered {error.status_code}.")
