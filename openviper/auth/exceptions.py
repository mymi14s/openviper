"""Authentication hook exceptions."""

from __future__ import annotations


class AuthHookError(Exception):
    """Base exception for authentication hook failures."""


class AuthHookReject(AuthHookError):
    """Raised by before-login hooks to reject authentication."""


class AuthHookConfigError(AuthHookError):
    """Raised when authentication hook registration is invalid."""


class AuthHookExecutionError(AuthHookError):
    """Raised when an authentication hook fails under a raising policy."""
