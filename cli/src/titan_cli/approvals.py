"""titan approvals, approve and reject: deciding approval requests (decision #118)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from titan_cli.account import TOKEN_REJECTED, signed_in
from titan_cli.client.models import ApprovalOut, Problem
from titan_cli.node import CliError, api_client


class UnreadableAnswerError(CliError):
    """The node answered 200 with something titan cannot read."""

    def __init__(self) -> None:
        super().__init__("the node sent an answer titan cannot read")


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


def _send(
    method: str,
    path: str,
    params: dict[str, str] | None = None,
    missing: str | None = None,
) -> Any:
    """The JSON of the node's answer to the request; CliError if it refused.

    missing is the error for a 404; without it, a 404 is like any other answer.

    The generated calls cannot be used: they read the answer into enums that
    refuse a value a newer node may send, and the answer would be lost.
    """
    saved = signed_in()
    client = api_client(saved.url, saved.token).get_httpx_client()

    response = client.request(method, path, params=params)

    if response.status_code == 200:
        try:
            return response.json()
        except ValueError:
            raise UnreadableAnswerError from None
    if response.status_code == 401:
        raise CliError(TOKEN_REJECTED)
    if response.status_code == 404 and missing:
        # Another user's request is not found either (development rules, section 9).
        raise CliError(missing)
    try:
        problem = Problem.from_dict(response.json())
    except (KeyError, TypeError, ValueError):
        raise CliError(f"the node answered {response.status_code}.") from None
    # A request decided before comes with its state (decision #121).
    if response.status_code == 409 and isinstance(problem.detail, str):
        raise CliError(problem.detail)
    raise CliError(f"the node answered {response.status_code}: {problem.title}")


def approvals_list() -> None:
    """Print every pending request of the signed-in user, oldest first."""
    requests: list[Approval] = []
    after: str | None = None
    while True:
        page = _send(
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
            _send(
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
