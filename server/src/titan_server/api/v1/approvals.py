"""Approval requests: calls waiting for Approve or Reject (decision #118)."""

import os
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field

from titan_server.agent.approvals import approve
from titan_server.api.dependencies import CurrentDevice, Session
from titan_server.api.problems import problems
from titan_server.domains.audit import approvals
from titan_server.domains.audit.models import (
    ActionClass,
    AuditEntry,
    Domain,
    EntryStatus,
)

DEFAULT_MAX_PAGE_SIZE = 100


def max_page_size() -> int:
    """The most items a page holds; see TITAN_DEFAULT_MAX_PAGE_SIZE (decision #83).

    NOTE: every user gets the node's default until users have settings; then
    a user's own limit comes first.
    """
    return int(os.environ.get("TITAN_DEFAULT_MAX_PAGE_SIZE", DEFAULT_MAX_PAGE_SIZE))


class ApprovalOut(BaseModel):
    """A call that waits, or waited, for the user's approval."""

    id: uuid.UUID = Field(description="The call's audit entry.")
    tool: str
    summary: str
    domain: Domain
    action_class: ActionClass
    status: EntryStatus
    created_at: datetime


class ApprovalPage(BaseModel):
    """A page of approval requests, oldest first (decision #124)."""

    items: list[ApprovalOut]
    next: str | None = Field(
        description="Send it back as `after` for the next page; null on the last."
    )


def approval_out(entry: AuditEntry) -> ApprovalOut:
    """The request as the API shows it; entry's attributes must be loaded."""
    return ApprovalOut(
        id=entry.id,
        tool=entry.tool,
        summary=entry.summary,
        domain=entry.domain,
        action_class=entry.action_class,
        status=entry.status,
        created_at=entry.created_at,
    )


router = APIRouter(prefix="/approvals")


@router.get("", responses=problems(401, 422))
async def list_approvals(
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
) -> ApprovalPage:
    """The signed-in user's pending approval requests, oldest first."""
    page_size = min(limit or max_page_size(), max_page_size())
    try:
        entries, cursor = await approvals.list_pending(
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
    return ApprovalPage(items=[approval_out(entry) for entry in entries], next=cursor)


@router.post("/{approval_id}/approve", responses=problems(401, 404, 409, 422))
async def approve_request(
    approval_id: uuid.UUID, device: CurrentDevice, session: Session
) -> ApprovalOut:
    """Approve a pending request: run its call as stored, and tell its thread.

    The answer is 200 whether the call ran or failed; `status` says which.
    """
    try:
        entry = await approve(session, device.user_id, approval_id)
    except approvals.ApprovalNotFoundError:
        raise HTTPException(404) from None
    except approvals.AlreadyDecidedError as error:
        raise HTTPException(409, str(error)) from None
    # A failed run's rollback may have expired the entry; read it again.
    await session.refresh(entry)
    return approval_out(entry)


@router.post("/{approval_id}/reject", responses=problems(401, 404, 409, 422))
async def reject_request(
    approval_id: uuid.UUID, device: CurrentDevice, session: Session
) -> ApprovalOut:
    """Reject a pending request: its call never runs, and its thread is told."""
    try:
        entry = await approvals.reject(session, device.user_id, approval_id)
    except approvals.ApprovalNotFoundError:
        raise HTTPException(404) from None
    except approvals.AlreadyDecidedError as error:
        raise HTTPException(409, str(error)) from None
    return approval_out(entry)
