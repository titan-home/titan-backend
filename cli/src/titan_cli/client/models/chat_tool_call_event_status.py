from enum import StrEnum


class ChatToolCallEventStatus(StrEnum):
    DENIED = "denied"
    DONE = "done"
    FAILED = "failed"
    PENDING = "pending"

    def __str__(self) -> str:
        return str(self.value)
