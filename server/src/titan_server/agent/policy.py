"""The policy: which mode a tool call runs in (decisions #10, #37, #38, #113)."""

from titan_server.domains.audit.models import ActionClass, Mode

# Decision #38; no class defaults to deny.
DEFAULT_MODES: dict[ActionClass, Mode] = {
    ActionClass.READ: Mode.AUTO,
    ActionClass.WRITE_INTERNAL: Mode.AUTO_UNDO,
    ActionClass.EXTERNAL: Mode.CONFIRM,
    ActionClass.DESTRUCTIVE: Mode.CONFIRM,
}


def mode_for(action_class: ActionClass, undoable: bool) -> Mode:
    """The mode a call of a tool with this class runs in.

    A tool that cannot be undone never runs as auto-undo; it waits for
    approval instead (decision #37).
    """
    mode = DEFAULT_MODES[action_class]
    return Mode.CONFIRM if (mode == Mode.AUTO_UNDO and not undoable) else mode
