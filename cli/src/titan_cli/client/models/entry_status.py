from enum import StrEnum


class EntryStatus(StrEnum):
    DENIED = "denied"
    DONE = "done"
    EXPIRED = "expired"
    FAILED = "failed"
    PENDING = "pending"
    REJECTED = "rejected"

    def __str__(self) -> str:
        return str(self.value)
