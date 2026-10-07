"""Entry point of the titan command."""

import argparse
import socket
import sys
from importlib.metadata import version

import httpx

from titan_cli.account import login, whoami
from titan_cli.chat import chat
from titan_cli.client.errors import UnexpectedStatus
from titan_cli.client.models import ActionClass, Domain, Mode
from titan_cli.node import CliError
from titan_cli.policy import policy_list, policy_reset, policy_set


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
    chat_parser = commands.add_parser(
        "chat", help="send a message in a new thread and print the reply"
    )
    chat_parser.add_argument("text", help="the message, quoted")
    policy_parser = commands.add_parser(
        "policy", help="what the agent may do on its own, per domain"
    )
    policy_commands = policy_parser.add_subparsers(dest="policy", required=True)
    policy_commands.add_parser(
        "list", help="show the mode every action class runs in, in every domain"
    )
    domains = [domain.value for domain in Domain]
    classes = [action_class.value for action_class in ActionClass]
    set_parser = policy_commands.add_parser(
        "set", help="set your own mode for one class in one domain"
    )
    set_parser.add_argument("domain", choices=domains)
    set_parser.add_argument(
        "action_class", metavar="class", choices=classes, help=", ".join(classes)
    )
    set_parser.add_argument(
        "mode",
        choices=[mode.value for mode in Mode],
        help="external and destructive can only be confirm or deny",
    )
    reset_parser = policy_commands.add_parser(
        "reset", help="return one class in one domain to its default mode"
    )
    reset_parser.add_argument("domain", choices=domains)
    reset_parser.add_argument(
        "action_class", metavar="class", choices=classes, help=", ".join(classes)
    )
    arguments = parser.parse_args(argv)

    try:
        if arguments.command == "login":
            login(arguments.url, arguments.name, arguments.dev)
        elif arguments.command == "chat":
            chat(arguments.text)
        elif arguments.command == "policy" and arguments.policy == "list":
            policy_list()
        elif arguments.command == "policy" and arguments.policy == "set":
            policy_set(arguments.domain, arguments.action_class, arguments.mode)
        elif arguments.command == "policy":
            policy_reset(arguments.domain, arguments.action_class)
        else:
            whoami()
    except CliError as error:
        sys.exit(f"titan: {error}")
    except httpx.TransportError as error:
        sys.exit(f"titan: cannot reach the node: {error}")
    except UnexpectedStatus as error:
        sys.exit(f"titan: the node answered {error.status_code}.")
