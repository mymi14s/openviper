"""Core permission checking logic without auth.models dependencies.

This module contains the permission checking interface that can be imported
by db.models without creating circular dependencies. The actual ContentType
lookup is deferred to the main permissions module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from openviper.core.context import current_user, ignore_permissions_ctx

if TYPE_CHECKING:
    from openviper.db.models import Model


class AuthPermissionError(Exception):
    """Raised when a user attempts an unauthorized action on a model."""

    pass


class PermissionChecker(Protocol):
    """Protocol for permission checking implementations."""

    async def is_model_protected(self, app_label: str, model_name: str) -> bool:
        """Check if a model has permission restrictions configured."""
        raise NotImplementedError


permission_checker: PermissionChecker | None = None


def set_permission_checker(checker: PermissionChecker) -> None:
    """Set the permission checker implementation."""
    globals()["permission_checker"] = checker


async def check_permission_for_model(
    model_cls: type[Model], action: str, ignore_permissions: bool = False
) -> None:
    """Check if the current request user is authorized to perform an action.

    Args:
        model_cls: The model class being accessed.
        action: 'create', 'read', 'write', 'update', or 'delete'.
        ignore_permissions: If True, bypass all permission checks.

    Raises:
        AuthPermissionError: If the user is unauthenticated or unauthorized.
    """
    if ignore_permissions or ignore_permissions_ctx.get():
        return
    if getattr(model_cls, "_app_name", "") == "auth":
        return

    app_label = getattr(model_cls, "_app_name", "default")
    model_name = getattr(model_cls, "_model_name", model_cls.__name__)
    model_label = f"{app_label}.{model_name}"

    if permission_checker is None:
        return

    is_protected = await permission_checker.is_model_protected(app_label, model_name)
    if not is_protected:
        return

    user = current_user.get()
    if user is None:
        return

    if getattr(user, "is_superuser", False):
        return

    if not await user.has_model_perm(model_label, action):
        raise AuthPermissionError(f"Unauthorized: Access denied '{action}' on {model_label}")


def __getattr__(name: str) -> object:
    """Return backward-compatible module attributes."""
    if name == "PermissionError":
        return AuthPermissionError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
