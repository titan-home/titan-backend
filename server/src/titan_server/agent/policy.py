"""The policy: which mode a tool call runs in (decisions #10, #37, #38, #113)."""

from titan_server.domains.audit.models import ActionClass, Mode
from titan_server.domains.policy.service import DEFAULT_MODES


def mode_for(action_class: ActionClass, undoable: bool, override: Mode | None) -> Mode:
    """The mode a call of a tool with this class runs in.

    override is the user's own mode for the class in the tool's domain, if
    they set one (decision #10). A tool that cannot be undone never runs as
    auto-undo; it waits for approval instead (decision #37).
    """
    mode = override if override is not None else DEFAULT_MODES[action_class]
    return Mode.CONFIRM if (mode == Mode.AUTO_UNDO and not undoable) else mode
