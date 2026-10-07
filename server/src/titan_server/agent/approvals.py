"""Approving a request: the node runs exactly the call it stores (decision #120).

Rejecting and listing need no tools and live in the audit domain
(titan_server.domains.audit.approvals).
"""

import logging
import uuid

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.agent import turn
from titan_server.agent.tool import ToolContext, run_call
from titan_server.domains.audit.approvals import lock_pending
from titan_server.domains.audit.models import AuditEntry, EntryStatus, call_record
from titan_server.domains.chat import service as chat
from titan_server.domains.chat.models import ToolCallRecord

logger = logging.getLogger(__name__)


async def approve(
    session: AsyncSession, user_id: uuid.UUID, entry_id: uuid.UUID
) -> AuditEntry:
    """Run the user's pending request exactly as stored, without the agent.

    The input is checked again by the tool's input model, and the call runs
    through run_call, so its changes are in the log and a failure keeps none
    of them (decisions #120, #122). The entry ends done or failed (decision
    #123), and its thread, if any, is told how it went. Raises
    ApprovalNotFoundError or AlreadyDecidedError; a failed call does not
    raise. The caller commits the session, which ends the lock (decision #121).
    """
    entry = await lock_pending(session, user_id, entry_id)
    # Read before the run: a failed run's rollback may expire the entry.
    summary, thread_id = entry.summary, entry.thread_id
    record = await _run(session, user_id, entry)
    if thread_id is not None:
        thread = await chat.get_thread(session, user_id, thread_id)
        outcome = "done" if record["ok"] else "failed"
        await chat.add_reply(
            session, thread, f"Approved: {summary} — {outcome}.", [record], None
        )
    await session.flush()
    return entry


async def _run(
    session: AsyncSession, user_id: uuid.UUID, entry: AuditEntry
) -> ToolCallRecord:
    """Run the entry's call if its tool and input are still good; its record."""
    # Read at the time of the call, so that a tool added or removed since the
    # request was made is seen as it is now.
    tool = next((tool for tool in turn.TOOLS if tool.name == entry.tool), None)
    if tool is None:
        entry.status = EntryStatus.FAILED
        return call_record(entry)
    try:
        tool_input = tool.input_model.model_validate(entry.input)
    except ValidationError:
        entry.status = EntryStatus.FAILED
        return call_record(entry)

    context = ToolContext(session=session, user_id=user_id, thread_id=entry.thread_id)
    try:
        await run_call(tool, context, entry, tool_input)
    except Exception as error:
        # run_call has left the entry failed and kept none of the call's
        # changes; the user learns it from the status and the thread. The
        # type only: an error's text may quote the user's data.
        logger.warning("An approved call failed: %s", type(error).__name__)
    return context.calls[-1]
