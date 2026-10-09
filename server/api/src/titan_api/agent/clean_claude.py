#!/usr/bin/env python3
"""Start Claude Code with an environment built from scratch (rules, section 14).

The Agent SDK gives its CLI every variable of the api process, and an
ANTHROPIC_API_KEY among them would switch every call to API billing. The SDK
runs this script as its CLI instead; it passes on only the variables named
here and starts the real CLI named by TITAN_CLAUDE_CLI. It uses only the
standard library, since it runs as a program of its own.
"""

import os
import sys

KEPT = (
    "HOME",
    "CLAUDE_CONFIG_DIR",
    "CLAUDE_CODE_OAUTH_TOKEN",
    # Set by the SDK for the CLI: who started it, and which SDK.
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_AGENT_SDK_VERSION",
)
PATH = "/usr/local/bin:/usr/bin:/bin"


def main() -> None:
    """Replace this process with the real CLI, given only the kept variables."""
    cli = os.environ["TITAN_CLAUDE_CLI"]
    environment = {name: os.environ[name] for name in KEPT if name in os.environ}
    environment["PATH"] = PATH
    # execve passes the environment directly: the token never shows in the
    # command line, which other processes could read.
    os.execve(cli, [cli, *sys.argv[1:]], environment)  # noqa: S606  no shell wanted


if __name__ == "__main__":
    main()
