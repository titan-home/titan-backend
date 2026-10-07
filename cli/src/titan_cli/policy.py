"""titan policy: the mode each action class runs in, per domain (decision #115)."""

from titan_cli.account import TOKEN_REJECTED, signed_in
from titan_cli.client.api.default import list_modes, reset_mode, set_mode
from titan_cli.client.models import (
    ActionClass,
    Domain,
    Mode,
    PolicyModeIn,
    PolicyModeOut,
    Problem,
)
from titan_cli.node import CliError, api_client


def _refused(result: Problem | None, what: str) -> CliError:
    """The error to show when the node did not do what was asked."""
    if isinstance(result, Problem) and result.status == 401:
        return CliError(TOKEN_REJECTED)
    # A mode below the floor (decision #116) comes with the reason.
    if isinstance(result, Problem) and isinstance(result.detail, str):
        return CliError(result.detail)
    reason = result.title if isinstance(result, Problem) else "no answer"
    return CliError(f"the node refused to {what}: {reason}")


def policy_list() -> None:
    """Print the mode every action class runs in, in every domain, and whose it is."""
    saved = signed_in()

    result = list_modes.sync(client=api_client(saved.url, saved.token))

    if not isinstance(result, list):
        raise _refused(result, "list the modes")
    width = max((len(mode.domain.value) for mode in result), default=0)
    for mode in result:
        whose = "yours" if mode.own else "default"
        print(
            f"{mode.domain.value:<{width}}  {mode.action_class.value:<14}"
            f"  {mode.mode.value:<9}  {whose}"
        )


def policy_set(domain: str, action_class: str, mode: str) -> None:
    """Make mode this user's own for action_class in domain."""
    saved = signed_in()

    result = set_mode.sync(
        Domain(domain),
        ActionClass(action_class),
        client=api_client(saved.url, saved.token),
        body=PolicyModeIn(mode=Mode(mode)),
    )

    if not isinstance(result, PolicyModeOut):
        raise _refused(result, "set the mode")
    print(f"{result.domain} {result.action_class}: {result.mode}")


def policy_reset(domain: str, action_class: str) -> None:
    """Return action_class in domain to its default mode."""
    saved = signed_in()

    result = reset_mode.sync(
        Domain(domain),
        ActionClass(action_class),
        client=api_client(saved.url, saved.token),
    )

    if isinstance(result, Problem):
        raise _refused(result, "reset the mode")
    print(f"{domain} {action_class}: back to the default")
