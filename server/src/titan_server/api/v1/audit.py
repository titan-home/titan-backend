"""The audit log: undoing an action from its entry (decision #135)."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from titan_server.api.dependencies import CurrentDevice, Session
from titan_server.api.problems import problems
from titan_server.domains.audit import undo
from titan_server.domains.audit.models import (
    ActionClass,
    AuditEntry,
    Domain,
    EntryStatus,
    Mode,
)


class AuditEntryOut(BaseModel):
    """One call in the user's audit log, or an undo (decisions #108, #131)."""

    id: uuid.UUID
    tool: str
    summary: str
    domain: Domain
    action_class: ActionClass
    mode: Mode | None = Field(
        description="The mode the policy ran the call in; null for an undo."
    )
    status: EntryStatus
    undoable: bool = Field(
        description="Whether the call's tool could be undone when it was called."
    )
    undoes_entry_id: uuid.UUID | None = Field(
        description="For an undo, the entry it took back; null otherwise."
    )
    created_at: datetime


def audit_entry_out(entry: AuditEntry) -> AuditEntryOut:
    """The entry as the API shows it; entry's attributes must be loaded."""
    return AuditEntryOut(
        id=entry.id,
        tool=entry.tool,
        summary=entry.summary,
        domain=entry.domain,
        action_class=entry.action_class,
        mode=entry.mode,
        status=entry.status,
        undoable=entry.undoable,
        undoes_entry_id=entry.undoes_entry_id,
        created_at=entry.created_at,
    )


router = APIRouter(prefix="/audit")


@router.post("/entries/{entry_id}/undo", responses=problems(401, 404, 409, 422))
async def undo_entry(
    entry_id: uuid.UUID, device: CurrentDevice, session: Session
) -> AuditEntryOut:
    """Undo an action from its entry, whole; answer with the undo's own entry.

    Every refusal is 409 with a plain detail: never ran, cannot be undone,
    already undone, older than one year, or changed later.
    """
    try:
        entry = await undo.undo(session, device.user_id, entry_id, datetime.now(UTC))
    except undo.EntryNotFoundError:
        raise HTTPException(404) from None
    except undo.UndoRefusedError as error:
        raise HTTPException(409, str(error)) from None
    # created_at comes from the database.
    await session.refresh(entry)
    return audit_entry_out(entry)
