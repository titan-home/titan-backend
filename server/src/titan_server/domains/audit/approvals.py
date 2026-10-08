"""Approval requests: calls in confirm mode waiting for their user (decision #111).

Every function acts for one user. Approving runs the call, which needs the
agent's tools, so it lives in titan_server.agent.approvals.

A request expires lazily (decision #125): expired_before is the creation time
at or before which a pending request is past its deadline. Whoever checks
marks it expired and tells its thread.
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
        super().__init__(
            "This request has expired."
            if status == EntryStatus.EXPIRED
            else f"This request is already decided: {status}."
        )
        self.status = status


async def lock_pending(
    session: AsyncSession,
    user_id: uuid.UUID,
    entry_id: uuid.UUID,
    expired_before: datetime,
) -> AuditEntry:
    """Lock the user's pending request until the transaction ends (decision #121).

    A second decision waits here for the first to commit, then finds it
    decided. Raises ApprovalNotFoundError or AlreadyDecidedError. A request
    past its deadline is marked expired before the error, and the caller
    commits that mark although the decision failed (decision #125).
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
    if entry.status == EntryStatus.PENDING and entry.created_at <= expired_before:
        await _expire(session, user_id, entry)
    if entry.status != EntryStatus.PENDING:
        raise AlreadyDecidedError(entry.status)
    return entry


async def reject(
    session: AsyncSession,
    user_id: uuid.UUID,
    entry_id: uuid.UUID,
    expired_before: datetime,
) -> AuditEntry:
    """Reject the user's pending request; its thread, if any, is told (decision #120).

    Raises ApprovalNotFoundError or AlreadyDecidedError, as lock_pending.
    """
    entry = await lock_pending(session, user_id, entry_id, expired_before)
    entry.status = EntryStatus.REJECTED
    await _tell_thread(session, user_id, entry, f"Rejected: {entry.summary}.")
    await session.flush()
    return entry


# NOTE: a request nobody looks at stays pending past its deadline; a sweep
# comes with the worker of stage 6 (decision #125).
async def expire_overdue(
    session: AsyncSession,
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
    expired_before: datetime,
) -> None:
    """Mark the thread's requests past their deadline expired, before a new turn."""
    entries = await session.scalars(
        select(AuditEntry)
        .where(
            AuditEntry.user_id == user_id,
            AuditEntry.thread_id == thread_id,
            AuditEntry.status == EntryStatus.PENDING,
            AuditEntry.created_at <= expired_before,
        )
        .order_by(AuditEntry.created_at, AuditEntry.id)
        # A request being decided right now is skipped once it is decided.
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    for entry in list(entries):
        await _expire(session, user_id, entry)
    await session.flush()


async def _expire(session: AsyncSession, user_id: uuid.UUID, entry: AuditEntry) -> None:
    """Mark a request expired and tell its thread (decision #126)."""
    entry.status = EntryStatus.EXPIRED
    await _tell_thread(session, user_id, entry, f"Expired: {entry.summary}.")


async def _tell_thread(
    session: AsyncSession, user_id: uuid.UUID, entry: AuditEntry, text: str
) -> None:
    """Add the node's message on what became of a request to its thread, if any."""
    if entry.thread_id is not None:
        thread = await chat.get_thread(session, user_id, entry.thread_id)
        await chat.add_reply(session, thread, text, [call_record(entry)], None)


def _cursor(entry: AuditEntry) -> str:
    """The opaque cursor after entry: its time and id (decision #124)."""
    raw = f"{entry.created_at.isoformat()}|{entry.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _parse_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """The time and id a cursor holds; raises ValueError for anything else."""
    # Every failure here, from bad base64 to a bad UUID, is a ValueError.
    created_at, entry_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
    return datetime.fromisoformat(created_at), uuid.UUID(entry_id)


# NOTE: a request whose turn commits after a client's cursor has passed its
# created_at is missed in that paging run and shows on the next listing;
# fine while one user rarely runs two turns at once.
async def list_pending(
    session: AsyncSession,
    user_id: uuid.UUID,
    limit: int,
    after: str | None,
    expired_before: datetime,
) -> tuple[list[AuditEntry], str | None]:
    """The user's pending requests, oldest first, and the cursor of the next page.

    after is a cursor this function returned; the next is None on the last
    page (decision #124). Requests past their deadline are left out, though
    not marked (decision #125). Raises ValueError for a limit below 1 or a
    malformed cursor.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    query = (
        select(AuditEntry)
        .where(
            AuditEntry.user_id == user_id,
            AuditEntry.status == EntryStatus.PENDING,
            AuditEntry.created_at > expired_before,
        )
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
