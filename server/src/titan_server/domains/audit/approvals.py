"""Approval requests: calls in confirm mode waiting for their user (decision #111).

Every function acts for one user. Approving runs the call, which needs the
agent's tools, so it lives in titan_server.agent.approvals.
"""

import base64
import uuid
from datetime import datetime

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.domains.audit.models import AuditEntry, EntryStatus, call_record
from titan_server.domains.chat import service as chat


class ApprovalNotFoundError(Exception):
    """No such request, or it belongs to another user; the two are never told apart."""


class AlreadyDecidedError(Exception):
    """The request is no longer pending; status is where it stands (decision #121)."""

    def __init__(self, status: EntryStatus) -> None:
        super().__init__(f"This request is already decided: {status}.")
        self.status = status


async def lock_pending(
    session: AsyncSession, user_id: uuid.UUID, entry_id: uuid.UUID
) -> AuditEntry:
    """Lock the user's pending request until the transaction ends (decision #121).

    A second decision waits here for the first to commit, then finds it
    decided. Raises ApprovalNotFoundError or AlreadyDecidedError.
    """
    entry = await session.scalar(
        select(AuditEntry)
        .where(AuditEntry.id == entry_id, AuditEntry.user_id == user_id)
        .with_for_update()
        # The status as the lock finds it, not as this session last saw it.
        .execution_options(populate_existing=True)
    )
    if entry is None:
        raise ApprovalNotFoundError
    if entry.status != EntryStatus.PENDING:
        raise AlreadyDecidedError(entry.status)
    return entry


async def reject(
    session: AsyncSession, user_id: uuid.UUID, entry_id: uuid.UUID
) -> AuditEntry:
    """Reject the user's pending request; its thread, if any, is told (decision #120).

    Raises ApprovalNotFoundError or AlreadyDecidedError.
    """
    entry = await lock_pending(session, user_id, entry_id)
    entry.status = EntryStatus.REJECTED
    if entry.thread_id is not None:
        thread = await chat.get_thread(session, user_id, entry.thread_id)
        await chat.add_reply(
            session,
            thread,
            f"Rejected: {entry.summary}.",
            [call_record(entry)],
            None,
        )
    await session.flush()
    return entry


def _cursor(entry: AuditEntry) -> str:
    """The opaque cursor after entry: its time and id (decision #124)."""
    raw = f"{entry.created_at.isoformat()}|{entry.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _parse_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """The time and id a cursor holds; raises ValueError for anything else."""
    # Every failure here, from bad base64 to a bad UUID, is a ValueError.
    created_at, entry_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
    return datetime.fromisoformat(created_at), uuid.UUID(entry_id)


# NOTE: pending requests older than 24 hours are listed too until they
# expire, which comes in step 7.
# NOTE: a request whose turn commits after a client's cursor has passed its
# created_at is missed in that paging run and shows on the next listing;
# fine while one user rarely runs two turns at once.
async def list_pending(
    session: AsyncSession, user_id: uuid.UUID, limit: int, after: str | None
) -> tuple[list[AuditEntry], str | None]:
    """The user's pending requests, oldest first, and the cursor of the next page.

    after is a cursor this function returned; the next is None on the last
    page (decision #124). Raises ValueError for a limit below 1 or a
    malformed cursor.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    query = (
        select(AuditEntry)
        .where(AuditEntry.user_id == user_id, AuditEntry.status == EntryStatus.PENDING)
        .order_by(AuditEntry.created_at, AuditEntry.id)
        # One more than a page tells whether another page follows.
        .limit(limit + 1)
    )
    if after is not None:
        query = query.where(
            tuple_(AuditEntry.created_at, AuditEntry.id) > _parse_cursor(after)
        )
    entries = list(await session.scalars(query))
    if len(entries) <= limit:
        return entries, None
    page = entries[:limit]
    return page, _cursor(page[-1])
