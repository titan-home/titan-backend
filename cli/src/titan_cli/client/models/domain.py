from enum import StrEnum


class Domain(StrEnum):
    TASKS = "tasks"

    def __str__(self) -> str:
        return str(self.value)
