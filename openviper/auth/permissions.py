"""Role-based permission enforcement logic.

This module provides backward-compatible exports and lazily registers the
ContentType-based permission checker with the core permission system.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from openviper.auth.permission_checker import get_permission_checker
from openviper.auth.permission_core import (
    AuthPermissionError,
    set_permission_checker,
)
from openviper.auth.permission_core import (
    check_permission_for_model as core_check_permission_for_model,
)

if TYPE_CHECKING:
    from openviper.db.models import Model

__all__ = ["PermissionError", "check_permission_for_model"]

checker_registered: list[bool] = [False]


async def check_permission_for_model(
    model_cls: type[Model], action: str, ignore_permissions: bool = False
) -> None:
    """Check if the current request user is authorized to perform an action.

    Lazily registers the ContentType permission checker on first use.

    Args:
        model_cls: The model class being accessed.
        action: 'create', 'read', 'write', 'update', or 'delete'.
        ignore_permissions: If True, bypass all permission checks.

    Raises:
        AuthPermissionError: If the user is unauthenticated or unauthorized.
    """
    if not checker_registered[0]:
        set_permission_checker(get_permission_checker())
        checker_registered[0] = True

    await core_check_permission_for_model(model_cls, action, ignore_permissions)


def __getattr__(name: str) -> object:
    """Return backward-compatible module attributes."""
    if name == "PermissionError":
        return AuthPermissionError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
