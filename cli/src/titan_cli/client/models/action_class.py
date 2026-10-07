from enum import StrEnum


class ActionClass(StrEnum):
    DESTRUCTIVE = "destructive"
    EXTERNAL = "external"
    READ = "read"
    WRITE_INTERNAL = "write-internal"

    def __str__(self) -> str:
        return str(self.value)
