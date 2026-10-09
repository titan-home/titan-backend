"""Asking Claude through the Agent SDK, with the owner's subscription (decision #7)."""

import os
import tempfile
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import claude_agent_sdk
from claude_agent_sdk import (
    ClaudeAgentOptions,
    Message,
    SdkMcpTool,
    create_sdk_mcp_server,
    query,
)

# The SDK runs this instead of its CLI, so that the CLI gets a clean
# environment (development rules, section 14).
CLEAN_CLAUDE = Path(__file__).with_name("clean_claude.py")
BUNDLED_CLI = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
TOOL_SERVER = "titan"
# Claude's steps in one turn, each a reply or a round of tool calls; a turn
# that loops stops here instead of spending the subscription's limits.
MAX_STEPS = 10


def strong_model() -> str:
    """The model for conversation (decision #33); TITAN_STRONG_MODEL overrides it."""
    return os.environ.get("TITAN_STRONG_MODEL", "opus")


def claude_options(
    system_prompt: str, tools: Sequence[SdkMcpTool[Any]], home: Path
) -> ClaudeAgentOptions:
    """How one turn runs Claude Code: our prompt and tools, nothing of its own.

    The OAuth token is read from the file named by TITAN_CLAUDE_TOKEN_FILE
    (decision #77).
    """
    token = Path(os.environ["TITAN_CLAUDE_TOKEN_FILE"]).read_text().strip()
    return ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=strong_model(),
        # None of Claude Code's own tools: no shell, no files.
        tools=[],
        setting_sources=[],
        mcp_servers={TOOL_SERVER: create_sdk_mcp_server(TOOL_SERVER, tools=[*tools])},
        allowed_tools=[f"mcp__{TOOL_SERVER}__{tool.name}" for tool in tools],
        max_turns=MAX_STEPS,
        include_partial_messages=True,
        cli_path=CLEAN_CLAUDE,
        env={
            "TITAN_CLAUDE_CLI": str(BUNDLED_CLI),
            "HOME": str(home),
            "CLAUDE_CONFIG_DIR": str(home / ".claude"),
            "CLAUDE_CODE_OAUTH_TOKEN": token,
        },
    )


async def ask_claude(
    system_prompt: str, prompt: str, tools: Sequence[SdkMcpTool[Any]]
) -> AsyncIterator[Message]:
    """Send one prompt and yield what comes back, the reply as it is written."""
    # Claude Code keeps its transcript and settings under HOME; a temporary
    # directory, on tmpfs in the container, takes them away after the turn.
    with tempfile.TemporaryDirectory(prefix="titan-claude-") as home:
        options = claude_options(system_prompt, tools, Path(home))
        async for message in query(prompt=prompt, options=options):
            yield message
