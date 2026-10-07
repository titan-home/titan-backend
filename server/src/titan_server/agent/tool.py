"""What every tool declares (development rules, section 14; decision #98)."""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, assert_never

from claude_agent_sdk import SdkMcpTool
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.agent.policy import mode_for
from titan_server.domains.audit.capture import finish_call, start_call
from titan_server.domains.audit.models import (
    ActionClass,
    AuditEntry,
    Domain,
    EntryStatus,
    Mode,
)
from titan_server.domains.chat.models import ToolCallRecord
from titan_server.domains.policy.service import get_override


@dataclass(frozen=True)
class ToolContext:
    """Whom a turn's calls act for, the session they work in, the calls made."""

    session: AsyncSession
    user_id: uuid.UUID
    # The thread the calls come from; None outside a chat (decision #112).
    thread_id: uuid.UUID | None
    # Every call that ran in this turn, in order, for the reply to keep.
    calls: list[ToolCallRecord] = field(default_factory=list)


@dataclass(frozen=True)
class Tool[Input: BaseModel]:
    """A tool the agent may call, with everything a person needs to judge it.

    NOTE: undoable only says whether the log can take a call back (decision
    #109); the undo itself comes later in stage 3.
    """

    name: str
    # What the model reads to decide when and how to call the tool.
    description: str
    action_class: ActionClass
    # Where a user's own mode for the class applies (decisions #10, #114).
    domain: Domain
    # Whether putting back what the log recorded undoes a call (decision
    # #109); a tool that cannot be undone never runs as auto-undo.
    undoable: bool
    # The input the model must send; it is checked before run is called.
    input_model: type[Input]
    # One line a person can approve, built from the input.
    summary: Callable[[Input], str]
    # Does the work for context's user; the text it returns goes to the model.
    run: Callable[[ToolContext, Input], Awaitable[str]]


async def run_call(
    tool: Tool[Any], context: ToolContext, entry: AuditEntry, tool_input: BaseModel
) -> str:
    """Run a call of tool for its entry, record how it went, return the tool's text."""
    record: ToolCallRecord = {
        "name": tool.name,
        "summary": entry.summary,
        "ok": False,
        "entry_id": str(entry.id),
    }
    # What the run changes in Audited objects becomes the entry's changes.
    start_call(context.session, entry)
    try:
        text = await tool.run(context, tool_input)
        entry.status = EntryStatus.DONE
        record["ok"] = True
    finally:
        await finish_call(context.session)
        context.calls.append(record)
    return text


def sdk_tool(tool: Tool[Any], context: ToolContext) -> SdkMcpTool[Any]:
    """The tool as the Agent SDK takes it, acting for context's user."""

    async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            tool_input = tool.input_model.model_validate(arguments)
        except ValidationError as error:
            return {"content": [{"type": "text", "text": str(error)}], "is_error": True}
        summary = tool.summary(tool_input)
        override = await get_override(
            context.session, context.user_id, tool.domain, tool.action_class
        )
        mode = mode_for(tool.action_class, tool.undoable, override)
        # Every call is in the audit log, those that do not run too (autonomy
        # spec, audit log 1 and 2); one that runs is failed until it returns.
        audit_entry = AuditEntry(
            id=uuid.uuid4(),
            user_id=context.user_id,
            thread_id=context.thread_id,
            tool=tool.name,
            summary=summary,
            mode=mode,
            action_class=tool.action_class,
            input=tool_input.model_dump(mode="json"),
            status=EntryStatus.FAILED,
        )
        context.session.add(audit_entry)
        match mode:
            case Mode.DENY:
                audit_entry.status = EntryStatus.DENIED
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "The user's settings say this call is not"
                                " allowed, so it did not run."
                            ),
                        }
                    ],
                    "is_error": True,
                }
            case Mode.CONFIRM:
                audit_entry.status = EntryStatus.PENDING
                # Waiting is not an error: the model tells the user to approve.
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "This call needs the user's approval and has not"
                                " run yet. Tell the user it is waiting for their"
                                " approval."
                            ),
                        }
                    ]
                }
            case Mode.AUTO | Mode.AUTO_UNDO:
                text = await run_call(tool, context, audit_entry, tool_input)
                return {"content": [{"type": "text", "text": text}]}
            case _:
                assert_never(mode)

    return SdkMcpTool(
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_model.model_json_schema(),
        handler=handler,
    )
