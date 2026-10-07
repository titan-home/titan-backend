"""Tests for the policy's modes (autonomy spec, modes and defaults; decision #38)."""

import pytest

from titan_server.agent.policy import DEFAULT_MODES, mode_for
from titan_server.domains.audit.models import ActionClass, Mode


@pytest.mark.parametrize(
    ("action_class", "mode"),
    [
        (ActionClass.READ, Mode.AUTO),
        (ActionClass.WRITE_INTERNAL, Mode.AUTO_UNDO),
        (ActionClass.EXTERNAL, Mode.CONFIRM),
        (ActionClass.DESTRUCTIVE, Mode.CONFIRM),
    ],
)
def test_each_class_has_its_default_mode(action_class: ActionClass, mode: Mode) -> None:
    """Defaults 1."""
    assert mode_for(action_class, undoable=True, override=None) == mode


def test_no_class_defaults_to_deny() -> None:
    """Defaults 4."""
    assert Mode.DENY not in DEFAULT_MODES.values()


def test_a_tool_without_an_undo_waits_for_approval_instead_of_auto_undo() -> None:
    """Modes 3: never auto-undo without an undo; treated as confirm."""
    assert (
        mode_for(ActionClass.WRITE_INTERNAL, undoable=False, override=None)
        == Mode.CONFIRM
    )


def test_a_read_needs_no_undo_to_run_at_once() -> None:
    assert mode_for(ActionClass.READ, undoable=False, override=None) == Mode.AUTO


def test_a_users_own_mode_replaces_the_default() -> None:
    """Defaults 2: confirm for write-internal in one domain."""
    assert (
        mode_for(ActionClass.WRITE_INTERNAL, undoable=True, override=Mode.CONFIRM)
        == Mode.CONFIRM
    )


def test_a_users_auto_undo_still_waits_for_a_tool_without_an_undo() -> None:
    """Modes 3 holds for a user's own mode too."""
    assert (
        mode_for(ActionClass.READ, undoable=False, override=Mode.AUTO_UNDO)
        == Mode.CONFIRM
    )
