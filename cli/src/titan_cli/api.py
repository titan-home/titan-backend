"""Sending a request to the node this device is signed in to, and reading its answer."""

from typing import Any

from titan_cli.account import TOKEN_REJECTED, signed_in
from titan_cli.client.models import Problem
from titan_cli.node import CliError, api_client


class UnreadableAnswerError(CliError):
    """The node answered 200 with something titan cannot read."""

    def __init__(self) -> None:
        super().__init__("the node sent an answer titan cannot read")


def send(
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
        # Another user's item is not found either (development rules, section 9).
        raise CliError(missing)
    try:
        problem = Problem.from_dict(response.json())
    except (KeyError, TypeError, ValueError):
        raise CliError(f"the node answered {response.status_code}.") from None
    # A refusal for the item's state comes with a plain detail, such as a
    # request decided before (decision #121).
    if response.status_code == 409 and isinstance(problem.detail, str):
        raise CliError(problem.detail)
    raise CliError(f"the node answered {response.status_code}: {problem.title}")
