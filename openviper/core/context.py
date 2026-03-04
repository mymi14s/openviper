"""Context variables for Openviper.

This module provides global context variables that track request-scoped state
such as the currently authenticated user.
"""

from __future__ import annotations

import contextvars
from typing import Any

# Tracks the User (or AnonymousUser) object for the current request
current_user: contextvars.ContextVar[Any | None] = contextvars.ContextVar(
    "current_user", default=None
)

# Tracks whether permissions should be ignored for the current execution context
ignore_permissions_ctx: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "ignore_permissions_ctx", default=False
)


def get_current_user() -> Any | None:
    """Get the currently authenticated user from the context.

    Returns None if no user is set (e.g. outside of a request context).
    """
    return current_user.get()


def set_current_user(user: Any) -> contextvars.Token[Any]:
    """Set the currently authenticated user in the context.

    Args:
        user: The user object, or AnonymousUser.

    Returns:
        A token that can be used to restore the previous value.
    """
    return current_user.set(user)
