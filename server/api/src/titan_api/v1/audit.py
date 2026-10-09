"""The audit log: the list of it and undoing from an entry (decisions #136, #135)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field

from titan_api.dependencies import CurrentDevice, Session
from titan_api.problems import problems
from titan_api.v1.approvals import (
    DEFAULT_MAX_PAGE_SIZE,
    expired_before,
    max_page_size,
)
from titan_core.domains.audit import log, undo
from titan_core.domains.audit.models import (
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


class AuditEntryPage(BaseModel):
    """A page of the user's audit log, newest first (decision #124)."""

    items: list[AuditEntryOut]
    next: str | None = Field(
        description="Send it back as `after` for the next page; null on the last."
    )


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


@router.get("/entries", responses=problems(401, 422))
async def list_entries(
    device: CurrentDevice,
    session: Session,
    # The maximum is the node's setting, so the contract names only the
    # default (decision #83).
    limit: Annotated[
        int | None,
        Query(
            ge=1,
            description=(
                "At most the node's maximum page size, larger is capped;"
                f" {DEFAULT_MAX_PAGE_SIZE} by default. Missing means the maximum."
            ),
        ),
    ] = None,
    after: Annotated[
        str | None, Query(description="The `next` of the page before.")
    ] = None,
) -> AuditEntryPage:
    """The signed-in user's audit log, newest first: every call and every undo."""
    page_size = min(limit or max_page_size(), max_page_size())
    try:
        entries, cursor = await log.list_entries(
            session, device.user_id, page_size, after
        )
    except ValueError:
        # Answered like any invalid input, naming the field (api/problems.py).
        raise RequestValidationError(
            [
                {
                    "loc": ("query", "after"),
                    "msg": "The cursor is not valid.",
                    "type": "value_error",
                }
            ]
        ) from None
    # A request nobody touched still says pending past its deadline; every
    # reader shows it expired, without writing on a GET (decision #125).
    deadline = expired_before(datetime.now(UTC))
    items = [
        audit_entry_out(entry).model_copy(update={"status": EntryStatus.EXPIRED})
        if entry.status == EntryStatus.PENDING and entry.created_at <= deadline
        else audit_entry_out(entry)
        for entry in entries
    ]
    return AuditEntryPage(items=items, next=cursor)


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
