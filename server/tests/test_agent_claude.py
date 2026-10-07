"""Tests for how the node starts Claude Code (decisions #7, #97; rules, section 14).

None of them calls Claude: a stand-in CLI prints what it was given.
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from titan_server.agent.claude import (
    BUNDLED_CLI,
    CLEAN_CLAUDE,
    claude_options,
    strong_model,
)
from titan_server.agent.tool import ToolContext, sdk_tool
from titan_server.agent.tools.tasks import create_task

TOKEN = "sk-ant-oat01-" + "t" * 20


@pytest.fixture
def stand_in_cli(tmp_path: Path) -> Path:
    """A CLI that prints its arguments and environment as JSON."""
    cli = tmp_path / "claude"
    # The environment it was started with, read from /proc: Python adds
    # LC_CTYPE to os.environ on its own when no locale is set (PEP 538).
    cli.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "raw = open('/proc/self/environ', 'rb').read().split(b'\\0')\n"
        "env = dict(v.decode().split('=', 1) for v in raw if v)\n"
        "print(json.dumps({'args': sys.argv[1:], 'env': env}))\n"
    )
    cli.chmod(0o755)
    return cli


def run_clean_claude(stand_in_cli: Path, environment: dict[str, str]) -> dict[str, Any]:
    completed = subprocess.run(  # noqa: S603  our own script
        [str(CLEAN_CLAUDE), "--print", "-v"],
        env={**environment, "TITAN_CLAUDE_CLI": str(stand_in_cli)},
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)  # type: ignore[no-any-return]


def test_no_anthropic_variable_reaches_claude_code(stand_in_cli: Path) -> None:
    """Rules, section 14: an API key would switch every call to API billing."""
    seen = run_clean_claude(
        stand_in_cli,
        {
            **os.environ,
            "ANTHROPIC_API_KEY": "sk-ant-api03-not-to-be-used",
            "ANTHROPIC_BASE_URL": "https://example.com",
            "TITAN_DATABASE_URL": "postgresql+psycopg://titan@db/titan",
            "CLAUDE_CODE_OAUTH_TOKEN": TOKEN,
            "HOME": "/run/titan-claude-x",
        },
    )

    assert not [name for name in seen["env"] if name.startswith("ANTHROPIC_")]
    assert "TITAN_DATABASE_URL" not in seen["env"]
    assert seen["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == TOKEN
    assert seen["env"]["HOME"] == "/run/titan-claude-x"


def test_only_the_listed_variables_reach_claude_code(stand_in_cli: Path) -> None:
    seen = run_clean_claude(
        stand_in_cli, {**os.environ, "CLAUDE_CODE_OAUTH_TOKEN": TOKEN}
    )

    assert set(seen["env"]) <= {
        "PATH",
        "HOME",
        "CLAUDE_CONFIG_DIR",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDE_AGENT_SDK_VERSION",
    }
    assert seen["args"] == ["--print", "-v"]


def test_the_clean_start_and_the_bundled_cli_can_be_run() -> None:
    # The SDK's own CLI lives inside the package; a new SDK version that moves
    # it fails here instead of on the node.
    for program in (CLEAN_CLAUDE, BUNDLED_CLI):
        assert program.stat().st_mode & stat.S_IXUSR, program


def test_claude_code_gets_our_prompt_and_tools_and_nothing_of_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decision #97: built-in tools off, no settings read from disk."""
    token_file = tmp_path / "claude_token"
    token_file.write_text(TOKEN + "\n")
    monkeypatch.setenv("TITAN_CLAUDE_TOKEN_FILE", str(token_file))
    context = ToolContext(session=None, user_id=None, thread_id=None)  # type: ignore[arg-type]

    options = claude_options("prompt", [sdk_tool(create_task, context)], tmp_path)

    assert (options.system_prompt, options.tools, options.setting_sources) == (
        "prompt",
        [],
        [],
    )
    assert options.allowed_tools == ["mcp__titan__create_task"]
    assert options.cli_path == CLEAN_CLAUDE
    assert options.env == {
        "TITAN_CLAUDE_CLI": str(BUNDLED_CLI),
        "HOME": str(tmp_path),
        "CLAUDE_CONFIG_DIR": str(tmp_path / ".claude"),
        "CLAUDE_CODE_OAUTH_TOKEN": TOKEN,
    }


def test_the_strong_model_is_opus_unless_the_node_says_otherwise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TITAN_STRONG_MODEL", raising=False)
    assert strong_model() == "opus"

    monkeypatch.setenv("TITAN_STRONG_MODEL", "sonnet")
    assert strong_model() == "sonnet"
