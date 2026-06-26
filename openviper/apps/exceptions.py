"""Exception classes for the OpenViper app lifecycle system."""

from __future__ import annotations


class AppLifecycleError(Exception):
    """Base exception for app lifecycle failures."""


class AppLifecycleConfigError(AppLifecycleError):
    """Raised when lifecycle.py defines invalid hook callables."""


class AppLifecycleImportError(AppLifecycleError):
    """Raised when lifecycle.py exists but fails to import."""


class AppReadyError(AppLifecycleError):
    """Raised when a ready() hook raises an exception."""

    def __init__(self, app_name: str, original_exception: BaseException) -> None:
        self.app_name = app_name
        self.original_exception = original_exception
        super().__init__(f"ready() hook failed for app '{app_name}': {original_exception}")


class AppStartupError(AppLifecycleError):
    """Raised when a startup() hook raises an exception.

    The *shutdown_errors* attribute collects any exceptions raised
    by shutdown hooks run during the cleanup of already-started apps.
    """

    def __init__(
        self,
        app_name: str,
        original_exception: BaseException,
        shutdown_errors: list[AppShutdownError] | None = None,
    ) -> None:
        self.app_name = app_name
        self.original_exception = original_exception
        self.shutdown_errors = shutdown_errors or []
        msg = f"startup() hook failed for app '{app_name}': {original_exception}"
        if self.shutdown_errors:
            msg += f"; {len(self.shutdown_errors)} shutdown error(s) during cleanup"
        super().__init__(msg)


class AppShutdownError(AppLifecycleError):
    """Raised when one or more shutdown() hooks fail."""

    def __init__(
        self,
        errors: list[tuple[str, BaseException]],
    ) -> None:
        self.errors = errors
        details = "; ".join(f"'{name}': {exc}" for name, exc in errors)
        super().__init__(f"{len(errors)} shutdown hook(s) failed: {details}")
