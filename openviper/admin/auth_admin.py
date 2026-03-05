"""Auto-registration of auth models in the admin panel.

Registers User, Permission, Role, UserRole, RolePermission, and ChangeHistory
models with the admin panel. ChangeHistory is read-only (no add/edit/delete).
"""

from __future__ import annotations

import contextlib

from openviper.admin.history import ChangeHistory
from openviper.admin.options import ModelAdmin
from openviper.admin.registry import AlreadyRegistered, admin
from openviper.auth import get_user_model
from openviper.auth.models import Permission, Role, RolePermission, UserRole

# ── User Admin ────────────────────────────────────────────────────────────


class UserAdmin(ModelAdmin):
    """Admin configuration for User model."""

    list_display = [
        "username",
        "email",
        "first_name",
        "last_name",
        "is_active",
        "is_staff",
        "is_superuser",
    ]
    list_filter = ["is_active", "is_staff", "is_superuser"]
    search_fields = ["username", "email", "first_name", "last_name"]
    exclude = ["password"]  # Exclude password from forms
    readonly_fields = ["created_at", "updated_at", "last_login"]
    sensitive_fields = ["password"]  # Never serialize/expose this field
    fieldsets = [
        ("Account", {"fields": ["username", "email"]}),
        (
            "Personal Info",
            {
                "fields": ["first_name", "last_name", "bio", "profile_image"],
                "classes": ["collapse"],
            },
        ),
        ("Status", {"fields": ["is_active", "is_staff", "is_superuser"]}),
        ("Dates", {"fields": ["created_at", "updated_at", "last_login"]}),
    ]


# ── Permission Admin ──────────────────────────────────────────────────────


class PermissionAdmin(ModelAdmin):
    """Admin configuration for Permission model."""

    list_display = ["name", "codename", "description"]
    search_fields = ["name", "codename"]


# ── Role Admin ────────────────────────────────────────────────────────────


class RoleAdmin(ModelAdmin):
    """Admin configuration for Role model."""

    list_display = ["name", "description"]
    search_fields = ["name"]


# ── UserRole Admin ────────────────────────────────────────────────────────


class UserRoleAdmin(ModelAdmin):
    """Admin configuration for UserRole model."""

    list_display = ["user_id", "role_id"]


# ── RolePermission Admin ──────────────────────────────────────────────────


class RolePermissionAdmin(ModelAdmin):
    """Admin configuration for RolePermission model."""

    list_display = ["role_id", "permission_id"]


# ── ChangeHistory Admin (Read-only) ───────────────────────────────────────


class ChangeHistoryAdmin(ModelAdmin):
    """Admin configuration for ChangeHistory model (read-only)."""

    list_display = [
        "model_name",
        "object_id",
        "action",
        "changed_by_username",
        "change_time",
    ]
    list_filter = ["action", "model_name"]
    search_fields = ["model_name", "object_repr", "changed_by_username"]
    readonly_fields = [
        "model_name",
        "object_id",
        "object_repr",
        "action",
        "changed_fields",
        "changed_by_id",
        "changed_by_username",
        "change_time",
        "change_message",
    ]

    def has_add_permission(self, request=None) -> bool:
        """Disable adding new history records."""
        return False

    def has_change_permission(self, request=None, obj=None) -> bool:
        """Disable editing history records."""
        return False

    def has_delete_permission(self, request=None, obj=None) -> bool:
        """Disable deleting history records."""
        return False


# ── Register all auth models ──────────────────────────────────────────────


def register_auth_models() -> None:
    """Register all auth models with the admin site."""

    User = get_user_model()  # noqa: N806

    # Register User model (may already be registered by project)
    with contextlib.suppress(AlreadyRegistered):
        admin.register(User, UserAdmin)

    # Register other auth models (may be called multiple times)
    models_to_register = [
        (Permission, PermissionAdmin),
        (Role, RoleAdmin),
        (UserRole, UserRoleAdmin),
        (RolePermission, RolePermissionAdmin),
        (ChangeHistory, ChangeHistoryAdmin),
    ]

    for model_class, admin_class in models_to_register:
        with contextlib.suppress(AlreadyRegistered):
            admin.register(model_class, admin_class)
