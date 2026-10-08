"""Undoing an action from its audit entry (decisions #109, #131 to #134, #137).

One undo serves every tool: it puts back what the entry's changes recorded,
and is itself an entry whose changes the capture catches (decision #110).
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from titan_server.db import Audited, Base
from titan_server.domains.audit.capture import finish_call, from_json, start_call
from titan_server.domains.audit.models import (
    AuditChange,
    AuditEntry,
    EntryStatus,
    call_record,
)
from titan_server.domains.chat import service as chat

# How long an action can be undone (decision #40); not a setting (decision #137).
# NOTE: entries older than this are only refused; moving them to the archive
# comes with the worker of stage 6 (decision #137).
UNDO_WINDOW = timedelta(days=365)

# Why an undo is refused, each answered 409 with its text (decision #135).
NEVER_RAN = "Cannot undo: this action never ran."
NOT_UNDOABLE = "Cannot undo: this action cannot be undone."
ALREADY_UNDONE = "Cannot undo: this action is already undone."
TOO_OLD = "Cannot undo: this action is older than one year."
CHANGED_LATER = "Cannot undo: something this action changed was changed later."

# The column the undo of a created object sets, moving it to the trash
# (decision #109).
DELETED_AT_COLUMN = "deleted_at"


class EntryNotFoundError(Exception):
    """No such entry, or it belongs to another user; the two are never told apart."""


class UndoRefusedError(Exception):
    """The entry cannot be undone now; the message is one of the texts above."""


def _all_models() -> dict[str, type[Any]]:
    """Every mapped model by its table name, for reading an entry's changes back."""
    return {
        mapper.class_.__tablename__: mapper.class_ for mapper in Base.registry.mappers
    }


# NOTE: only the latest action on an object can be undone: an earlier one
# finds the object at a later version; undoing step by step backwards is
# decided with the edit tools of stage 6 (decision #134).
async def undo(
    session: AsyncSession, user_id: uuid.UUID, entry_id: uuid.UUID, now: datetime
) -> AuditEntry:
    """Undo the user's action whole, or refuse whole; return the undo's entry.

    Refused, in this order, when the action never ran (status not done), its
    tool could not be undone, it is already undone, or it is older than
    UNDO_WINDOW at now; then when any object it changed was changed later.
    Raises EntryNotFoundError or UndoRefusedError, before anything is written.

    Undoing puts back what the entry's changes recorded: old field values
    return, and a created object goes to the trash, its deleted_at set to now
    (decision #109). The undo's own entry, done and undoable (decision #132),
    points to the undone one; the undone entry itself is not changed
    (decision #111). Its thread, if any, gets "Undone: <summary>." (decision
    #133). The caller commits the session.
    """
    audit_entry = await session.scalar(
        select(AuditEntry)
        .where(AuditEntry.id == entry_id, AuditEntry.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if audit_entry is None:
        raise EntryNotFoundError
    if audit_entry.status != EntryStatus.DONE:
        raise UndoRefusedError(NEVER_RAN)
    if not audit_entry.undoable:
        raise UndoRefusedError(NOT_UNDOABLE)

    earlier_undo = await session.scalar(
        select(AuditEntry).where(AuditEntry.undoes_entry_id == entry_id)
    )
    if earlier_undo is not None:
        raise UndoRefusedError(ALREADY_UNDONE)

    if now - audit_entry.created_at >= UNDO_WINDOW:
        raise UndoRefusedError(TOO_OLD)

    changes = await session.scalars(
        select(AuditChange)
        .where(AuditChange.entry_id == audit_entry.id)
        # A fixed order, so two undos cannot deadlock (decision #134).
        .order_by(AuditChange.table_name, AuditChange.object_id)
    )
    models = _all_models()
    found: list[tuple[AuditChange, Audited]] = []
    for change in list(changes):
        obj = await session.get(
            models[change.table_name],
            change.object_id,
            with_for_update=True,
            populate_existing=True,
        )
        # Gone, or changed by something after this action.
        if not isinstance(obj, Audited) or obj.version != change.version:
            raise UndoRefusedError(CHANGED_LATER)
        found.append((change, obj))

    undo_entry = AuditEntry(
        user_id=user_id,
        thread_id=audit_entry.thread_id,
        tool="undo",
        summary=f"Undo: {audit_entry.summary}",
        mode=None,
        action_class=audit_entry.action_class,
        domain=audit_entry.domain,
        status=EntryStatus.DONE,
        input={},
        undoable=True,
        undoes_entry_id=audit_entry.id,
    )
    session.add(undo_entry)

    start_call(session, undo_entry)
    for change, item in found:
        if change.before is None:
            setattr(item, DELETED_AT_COLUMN, now)
        else:
            for name, value in change.before.items():
                parsed_value = from_json(
                    Base.metadata.tables[change.table_name].c[name], value
                )
                setattr(item, name, parsed_value)
    await finish_call(session)

    if audit_entry.thread_id is not None:
        thread = await chat.get_thread(session, user_id, audit_entry.thread_id)
        await chat.add_reply(
            session,
            thread,
            f"Undone: {audit_entry.summary}.",
            [call_record(undo_entry)],
            None,
        )

    await session.flush()
    return undo_entry
