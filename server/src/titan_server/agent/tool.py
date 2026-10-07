"""What every tool declares (development rules, section 14; decision #98)."""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import SdkMcpTool
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.domains.audit.capture import finish_call, start_call
from titan_server.domains.audit.models import ActionClass, AuditEntry, EntryStatus
from titan_server.domains.chat.models import ToolCallRecord


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

    NOTE: no undo yet, although decision #98 lists it; it comes in stage 3,
    together with the policy and the audit log that use it.
    """

    name: str
    # What the model reads to decide when and how to call the tool.
    description: str
    action_class: ActionClass
    # The input the model must send; it is checked before run is called.
    input_model: type[Input]
    # One line a person can approve, built from the input.
    summary: Callable[[Input], str]
    # Does the work for context's user; the text it returns goes to the model.
    run: Callable[[ToolContext, Input], Awaitable[str]]


def sdk_tool(tool: Tool[Any], context: ToolContext) -> SdkMcpTool[Any]:
    """The tool as the Agent SDK takes it, acting for context's user."""

    async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            tool_input = tool.input_model.model_validate(arguments)
        except ValidationError as error:
            return {"content": [{"type": "text", "text": str(error)}], "is_error": True}
        summary = tool.summary(tool_input)
        # Every call that runs is in the audit log, failed ones too (autonomy
        # spec, audit log 1); it is failed until the run returns.
        entry = AuditEntry(
            id=uuid.uuid4(),
            user_id=context.user_id,
            thread_id=context.thread_id,
            tool=tool.name,
            action_class=tool.action_class,
            input=tool_input.model_dump(mode="json"),
            summary=summary,
            status=EntryStatus.FAILED,
        )
        context.session.add(entry)
        record: ToolCallRecord = {
            "name": tool.name,
            "summary": summary,
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
        return {"content": [{"type": "text", "text": text}]}

    return SdkMcpTool(
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_model.model_json_schema(),
        handler=handler,
    )
