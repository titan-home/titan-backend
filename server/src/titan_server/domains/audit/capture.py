"""Catching what a tool call changes, from the session as it flushes (decision #110).

While a call is current, every flush adds the changes of Audited objects to
it; finish_call turns them into one AuditChange per object (decision #108).
Values are stored in JSONB as Pydantic writes them in JSON mode, by the
column's Python type, and read back the same way for an undo.
"""

import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import ColumnElement, event, inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstanceState, Session

from titan_server.db import Audited, Base
from titan_server.domains.audit.models import AuditChange, AuditEntry


@dataclass
class _Change:
    """What the current call changed in one object so far."""

    table_name: str
    object_id: uuid.UUID
    # None while the object did not exist before the call: it was created in it.
    before: dict[str, Any] | None
    # None once the object is deleted.
    after: dict[str, Any] | None
    version: int


AUDIT_ENTRY = "audit_entry"
AUDIT_CHANGES = "audit_changes"


def to_json(column: ColumnElement[Any], value: Any) -> Any:
    """The value as it is kept in JSONB: a UUID or a time as a string."""
    if value is None:
        return None
    return TypeAdapter(column.type.python_type).dump_python(value, mode="json")


def from_json(column: ColumnElement[Any], value: Any) -> Any:
    """The value back in the column's Python type, for an undo."""
    if value is None:
        return None
    return TypeAdapter(column.type.python_type).validate_python(value)


def start_call(session: AsyncSession, entry: AuditEntry) -> None:
    """Make entry the current call: what the session flushes from now is its."""
    session.info[AUDIT_ENTRY] = entry
    session.info[AUDIT_CHANGES] = {}


def _audited(objects: Iterable[Any]) -> Iterator[InstanceState[Base]]:
    """The state of every Audited object among objects; the rest are not logged."""
    for obj in objects:
        # Base as well, so that mypy knows the object is mapped.
        if isinstance(obj, Audited) and isinstance(obj, Base):
            yield inspect(obj)


def _row(state: InstanceState[Base]) -> dict[str, Any]:
    """Every loaded column of an object, as JSON, without its version."""
    return {
        prop.key: to_json(prop.columns[0], state.dict[prop.key])
        for prop in state.mapper.column_attrs
        if prop.key in state.dict and prop.key != "version"
    }


def _changed_fields(
    state: InstanceState[Base],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The fields this flush changed in an object, as JSON: before and after."""
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for prop in state.mapper.column_attrs:
        if prop.key == "version":
            continue
        history = state.attrs[prop.key].history
        if not history.has_changes():
            continue
        column = prop.columns[0]
        # An empty side of the history is NULL: a field set from or to it.
        old = history.deleted[0] if history.deleted else None
        new = history.added[0] if history.added else None
        before[prop.key] = to_json(column, old)
        after[prop.key] = to_json(column, new)
    return before, after


def _key(state: InstanceState[Base]) -> tuple[str, uuid.UUID]:
    """Which object a change is about: its table and its id."""
    return (state.class_.__tablename__, state.dict["id"])


@event.listens_for(Session, "after_flush")
def _collect(session: Session, flush_context: Any) -> None:
    """Add what this flush changed to the current call.

    A call may flush several times, so an object seen before is merged: the
    first old value of each field is kept, the latest new one wins.
    """
    # A flush outside a tool call is not the log's business.
    if AUDIT_ENTRY not in session.info:
        return
    changes: dict[tuple[str, uuid.UUID], _Change] = session.info[AUDIT_CHANGES]
    # Created: nothing before, the whole row after. *_key(state) fills
    # table_name and object_id.
    for state in _audited(session.new):
        changes[_key(state)] = _Change(
            *_key(state), before=None, after=_row(state), version=state.dict["version"]
        )
    # Changed: only the fields this flush changed.
    for state in _audited(session.dirty):
        before, after = _changed_fields(state)
        if not after:
            # Assigned the value it already had: nothing changed.
            continue
        change = changes.get(_key(state))
        # The first change of this object in the call.
        if change is None:
            changes[_key(state)] = _Change(
                *_key(state), before=before, after=after, version=state.dict["version"]
            )
            continue
        # Seen in an earlier flush: the first old value of a field stays, the
        # latest new one wins. An object created in this call has no before.
        if change.before is not None:
            for name, value in before.items():
                change.before.setdefault(name, value)
        if change.after is not None:
            change.after.update(after)
        change.version = state.dict["version"]
    # Deleted: the whole row before, nothing after.
    for state in _audited(session.deleted):
        change = changes.get(_key(state))
        # Not touched earlier in the call.
        if change is None:
            changes[_key(state)] = _Change(
                *_key(state),
                before=_row(state),
                after=None,
                version=state.dict["version"],
            )
            continue
        # The whole row as it was before the call: values changed earlier in
        # the call are put back to their first old ones.
        if change.before is not None:
            change.before = _row(state) | change.before
        change.after = None
        change.version = state.dict["version"]


async def finish_call(session: AsyncSession) -> None:
    """Flush, add one AuditChange per changed object to the current entry, end it."""
    # The last changes still in memory pass through _collect.
    await session.flush()

    # End the call first: the AuditChange rows added below are not its changes.
    entry: AuditEntry = session.info.pop(AUDIT_ENTRY)
    changes: dict[tuple[str, uuid.UUID], _Change] = session.info.pop(AUDIT_CHANGES)

    # One row per object the call changed (decision #108).
    for change in changes.values():
        if change.before is None and change.after is None:
            # Created and deleted within the call: nothing to keep or undo.
            continue
        session.add(
            AuditChange(
                entry_id=entry.id,
                table_name=change.table_name,
                object_id=change.object_id,
                before=change.before,
                after=change.after,
                version=change.version,
            )
        )
