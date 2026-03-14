"""Permission checking for admin API operations.

Provides fine-grained permission checking for admin CRUD operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openviper.db.models import Model
    from openviper.http.request import Request


def check_admin_access(request: Request) -> bool:
    """Check if user has access to admin panel.

    Args:
        request: The current request.

    Returns:
        True if user can access admin.
    """
    user = getattr(request, "user", None)
    if user is None:
        return False

    if not getattr(user, "is_authenticated", False):
        return False

    return getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)


def check_model_permission(
    request: Request,
    model_class: type[Model],
    action: str,
) -> bool:
    """Check if user has permission for a model action.

    Args:
        request: The current request.
        model_class: The model class.
        action: One of 'view', 'add', 'change', 'delete'.

    Returns:
        True if user has permission.
    """
    user = getattr(request, "user", None)
    if user is None:
        return False

    # Superusers have all permissions
    if getattr(user, "is_superuser", False):
        return True

    # Staff users have basic CRUD permissions
    if getattr(user, "is_staff", False):
        return True

    # Build permission codename (for future use)
    # app_name = getattr(model_class, "_app_name", "")
    # model_name = model_class.__name__.lower()
    # Permission codename would be: f"{app_name}.{action}_{model_name}"

    # Check user permissions (if has_perm is available)
    # This would need to be async for OpenViper
    # Simplified synchronous check for now
    return hasattr(user, "has_perm")


def check_object_permission(
    request: Request,
    obj: Model,
    action: str,
) -> bool:
    """Check if user has permission for a specific object.

    Args:
        request: The current request.
        obj: The model instance.
        action: One of 'view', 'change', 'delete'.

    Returns:
        True if user has permission.
    """
    user = getattr(request, "user", None)
    if user is None:
        return False

    # Superusers have all permissions
    if getattr(user, "is_superuser", False):
        return True

    # Check model-level permission first
    return check_model_permission(request, obj.__class__, action)
    # Object-level permissions are delegated to model-level checks above


class PermissionChecker:
    """Utility class for checking admin permissions.

    Provides a more object-oriented interface for permission checking.
    """

    def __init__(self, request: Request) -> None:
        self.request = request
        self.user = getattr(request, "user", None)

    @property
    def is_authenticated(self) -> bool:
        """Check if user is authenticated."""
        if self.user is None:
            return False
        return getattr(self.user, "is_authenticated", False)

    @property
    def is_staff(self) -> bool:
        """Check if user is staff."""
        if self.user is None:
            return False
        return getattr(self.user, "is_staff", False)

    @property
    def is_superuser(self) -> bool:
        """Check if user is superuser."""
        if self.user is None:
            return False
        return getattr(self.user, "is_superuser", False)

    @property
    def has_admin_access(self) -> bool:
        """Check if user can access admin."""
        return self.is_authenticated and (self.is_staff or self.is_superuser)

    def can_view(self, model_class: type[Model]) -> bool:
        """Check if user can view model instances."""
        return check_model_permission(self.request, model_class, "view")

    def can_add(self, model_class: type[Model]) -> bool:
        """Check if user can add model instances."""
        return check_model_permission(self.request, model_class, "add")

    def can_change(self, model_class: type[Model], obj: Model | None = None) -> bool:
        """Check if user can change model instances."""
        if obj is not None:
            return check_object_permission(self.request, obj, "change")
        return check_model_permission(self.request, model_class, "change")

    def can_delete(self, model_class: type[Model], obj: Model | None = None) -> bool:
        """Check if user can delete model instances."""
        if obj is not None:
            return check_object_permission(self.request, obj, "delete")
        return check_model_permission(self.request, model_class, "delete")
