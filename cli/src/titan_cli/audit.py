"""titan undo and titan log: undoing an action, and listing the audit log."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from titan_cli.api import UnreadableAnswerError, send
from titan_cli.client.models import AuditEntryOut
from titan_cli.node import CliError


@dataclass(frozen=True)
class NewerEntry:
    """An entry with a status, domain, class or mode this CLI does not know yet.

    A newer node may add values (development rules, section 9); the entry is
    still shown, with those values as the node sent them.
    """

    id: UUID
    summary: str
    domain: str
    action_class: str
    mode: str | None
    status: str
    created_at: datetime


Entry = AuditEntryOut | NewerEntry


def _entry(fields: Any) -> Entry:
    """The entry in the node's JSON; CliError if titan cannot read it."""
    try:
        try:
            return AuditEntryOut.from_dict(fields)
        except ValueError:
            # The generated enums refuse a value they do not know.
            mode = fields["mode"]
            return NewerEntry(
                UUID(fields["id"]),
                str(fields["summary"]),
                str(fields["domain"]),
                str(fields["action_class"]),
                None if mode is None else str(mode),
                str(fields["status"]),
                datetime.fromisoformat(fields["created_at"]),
            )
    except (KeyError, TypeError, ValueError):
        raise UnreadableAnswerError from None


def log(after: str | None) -> None:
    """Print one page of the signed-in user's audit log, newest first."""
    page = send(
        "GET", "/api/v1/audit/entries", {"after": after} if after is not None else None
    )
    try:
        entries = [_entry(fields) for fields in page["items"]]
        more = page["next"]
    except (KeyError, TypeError):
        raise UnreadableAnswerError from None

    if not entries:
        print("Your audit log is empty.")
        return
    # The generated model takes a summary that is not text as it comes.
    width = max(len(str(entry.summary)) for entry in entries)
    for entry in entries:
        kind = f"{entry.domain}/{entry.action_class}"
        created = entry.created_at.isoformat(" ", "minutes")
        # An undo has no mode: nothing decided how it ran.
        mode = entry.mode if entry.mode is not None else "-"
        print(
            f"{entry.id}  {created}  {entry.summary!s:<{width}}  {kind}  {mode}"
            f"  {entry.status}"
        )
    if more is not None:
        print(f"More: titan log --after {more}")


def undo(entry_id: UUID) -> None:
    """Undo the action whole and print the undo, or why the node refused it."""
    try:
        answer = send(
            "POST",
            f"/api/v1/audit/entries/{entry_id}/undo",
            missing=f"there is no action {entry_id} in your log",
        )
        print(f"{answer['summary']} — {answer['status']}.")
    except (UnreadableAnswerError, KeyError, TypeError):
        # The node answered 200, so the action may already be undone: undoing
        # again is not the way to find out.
        raise CliError(
            "the node's answer could not be read; the action may have been undone"
        ) from None
