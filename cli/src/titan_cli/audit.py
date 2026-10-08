"""titan undo: undoing an action from its audit entry (decisions #135, #136)."""

from uuid import UUID

from titan_cli.api import UnreadableAnswerError, send
from titan_cli.node import CliError


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
