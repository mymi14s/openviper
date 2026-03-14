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


class PermissionError(Exception):  # noqa: A001
    """Raised when a user attempts an unauthorized action on a model."""

    pass


class PermissionChecker(Protocol):
    """Protocol for permission checking implementations."""

    async def is_model_protected(self, app_label: str, model_name: str) -> bool:
        """Check if a model has permission restrictions configured."""
        ...  # pylint: disable=unnecessary-ellipsis


# Global permission checker instance (set by permissions module)
_permission_checker: PermissionChecker | None = None


def set_permission_checker(checker: PermissionChecker) -> None:
    """Set the global permission checker implementation."""
    global _permission_checker
    _permission_checker = checker


async def check_permission_for_model(
    model_cls: type[Model], action: str, ignore_permissions: bool = False
) -> None:
    """Check if the current request user is authorized to perform an action.

    Args:
        model_cls: The model class being accessed.
        action: 'create', 'read', 'write', 'update', or 'delete'.
        ignore_permissions: If True, bypass all permission checks.

    Raises:
        PermissionError: If the user is unauthenticated or unauthorized.
    """
    if ignore_permissions or ignore_permissions_ctx.get():
        return
    if getattr(model_cls, "_app_name", "") == "auth":
        return

    # Get model info
    app_label = getattr(model_cls, "_app_name", "default")
    model_name = getattr(model_cls, "_model_name", model_cls.__name__)
    model_label = f"{app_label}.{model_name}"

    # Check if model is protected
    if _permission_checker is None:
        # No checker registered yet (early import), skip permission check
        return

    is_protected = await _permission_checker.is_model_protected(app_label, model_name)
    if not is_protected:
        return

    # Bypass check if no user context is set (e.g. CLI, management commands)
    user = current_user.get()
    if user is None:
        return

    # Bypass check if user is a superuser
    if getattr(user, "is_superuser", False):
        return

    # Enforce permissions
    if not await user.has_model_perm(model_label, action):
        raise PermissionError(f"Unauthorized: Access denied '{action}' on {model_label}")
