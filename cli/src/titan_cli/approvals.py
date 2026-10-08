"""titan approvals, approve and reject: deciding approval requests (decision #118)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from titan_cli.api import UnreadableAnswerError, send
from titan_cli.client.models import ApprovalOut
from titan_cli.node import CliError


@dataclass(frozen=True)
class NewerApproval:
    """A request with a status, domain or class this CLI does not know yet.

    A newer node may add values (development rules, section 9); the request
    is still shown, with those values as the node sent them.
    """

    id: UUID
    summary: str
    domain: str
    action_class: str
    status: str
    expires_at: datetime


Approval = ApprovalOut | NewerApproval


def _approval(fields: Any) -> Approval:
    """The request in the node's JSON; CliError if titan cannot read it."""
    try:
        try:
            return ApprovalOut.from_dict(fields)
        except ValueError:
            # The generated enums refuse a value they do not know.
            return NewerApproval(
                UUID(fields["id"]),
                str(fields["summary"]),
                str(fields["domain"]),
                str(fields["action_class"]),
                str(fields["status"]),
                datetime.fromisoformat(fields["expires_at"]),
            )
    except (KeyError, TypeError, ValueError):
        raise UnreadableAnswerError from None


def approvals_list() -> None:
    """Print every pending request of the signed-in user, oldest first."""
    requests: list[Approval] = []
    after: str | None = None
    while True:
        page = send(
            "GET", "/api/v1/approvals", {"after": after} if after is not None else None
        )
        try:
            requests += [_approval(fields) for fields in page["items"]]
            sent, after = after, page["next"]
        except (KeyError, TypeError):
            raise UnreadableAnswerError from None
        if after is None:
            break
        if after == sent:
            # Asking again would bring the same page for ever.
            raise CliError("the node sent the same page twice")

    if not requests:
        print("No approval requests are waiting.")
        return
    # The generated model takes a summary that is not text as it comes.
    width = max(len(str(request.summary)) for request in requests)
    for request in requests:
        kind = f"{request.domain}/{request.action_class}"
        expires = request.expires_at.isoformat(" ", "minutes")
        print(f"{request.id}  {request.summary!s:<{width}}  {kind}  expires {expires}")


def _decide(approval_id: UUID, decision: str) -> Approval:
    """Send the decision, approve or reject, and return the decided request."""
    try:
        return _approval(
            send(
                "POST",
                f"/api/v1/approvals/{approval_id}/{decision}",
                missing=f"there is no approval request {approval_id}",
            )
        )
    except UnreadableAnswerError:
        # The node answered 200, so the call may already have run: sending
        # the decision again is not the way to find out.
        raise CliError(
            "the node's answer could not be read; the request may have been"
            " decided, run titan approvals"
        ) from None


def approve(approval_id: UUID) -> None:
    """Approve the request and print how its call ended: done or failed.

    A call that failed is an outcome of the decision, not an error of this
    command, as a failed call in titan chat is.
    """
    request = _decide(approval_id, "approve")
    print(f"Approved: {request.summary} — {request.status}.")


def reject(approval_id: UUID) -> None:
    """Reject the request: its call never runs."""
    request = _decide(approval_id, "reject")
    print(f"Rejected: {request.summary}.")
