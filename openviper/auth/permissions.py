"""Role-based permission enforcement logic.

This module provides backward-compatible exports and lazily registers the
ContentType-based permission checker with the core permission system.
"""

from __future__ import annotations

# Re-export core functionality
from openviper.auth.permission_core import (
    PermissionError as OVPermissionError,
)
from openviper.auth.permission_core import (
    check_permission_for_model as _check_permission_for_model,
)
from openviper.auth.permission_core import (
    set_permission_checker,
)
from openviper.auth.permission_checker import get_permission_checker

PermissionError = OVPermissionError  # noqa: A001

__all__ = ["PermissionError", "check_permission_for_model"]

_checker_registered = False


async def check_permission_for_model(
    model_cls, action: str, ignore_permissions: bool = False
) -> None:
    """Check if the current request user is authorized to perform an action.

    Lazily registers the ContentType permission checker on first use.

    Args:
        model_cls: The model class being accessed.
        action: 'create', 'read', 'write', 'update', or 'delete'.
        ignore_permissions: If True, bypass all permission checks.

    Raises:
        PermissionError: If the user is unauthenticated or unauthorized.
    """
    global _checker_registered
    if not _checker_registered:
        set_permission_checker(get_permission_checker())
        _checker_registered = True

    await _check_permission_for_model(model_cls, action, ignore_permissions)
