from enum import StrEnum


class Mode(StrEnum):
    AUTO = "auto"
    AUTO_UNDO = "auto-undo"
    CONFIRM = "confirm"
    DENY = "deny"

    def __str__(self) -> str:
        return str(self.value)
