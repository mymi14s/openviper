"""Exception hierarchy for the tasks subsystem."""

from __future__ import annotations


class OpenViperTasksError(Exception):
    """Base exception for all task subsystem errors."""

    __slots__ = ()


class OpenViperTasksConfigurationError(OpenViperTasksError):
    """Raised when ``settings.TASKS`` fails structural validation."""

    __slots__ = ("errors",)

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("\n".join(f"  - {e}" for e in errors))


class ResultsBackendDisabledError(OpenViperTasksError):
    """Raised when ``.get_result()`` is called without a results backend."""

    __slots__ = ()
