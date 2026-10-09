"""Reading the audit log: the user's entries, newest first (decision #136).

Every function acts for one user.
"""

import uuid

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from titan_core.domains.audit.models import AuditEntry
from titan_core.domains.audit.paging import cursor, parse_cursor


async def list_entries(
    session: AsyncSession,
    user_id: uuid.UUID,
    limit: int,
    after: str | None,
) -> tuple[list[AuditEntry], str | None]:
    """The user's entries of every status, undos included, newest first.

    after is a cursor this function returned; the next is None on the last
    page (decision #124). Raises ValueError for a limit below 1 or a
    malformed cursor.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    query = (
        select(AuditEntry)
        .where(AuditEntry.user_id == user_id)
        .order_by(AuditEntry.created_at.desc(), AuditEntry.id.desc())
        # One more than a page tells whether another page follows.
        .limit(limit + 1)
    )
    if after is not None:
        query = query.where(
            tuple_(AuditEntry.created_at, AuditEntry.id) < parse_cursor(after)
        )
    entries = list(await session.scalars(query))
    if len(entries) <= limit:
        return entries, None
    page = entries[:limit]
    return page, cursor(page[-1])
