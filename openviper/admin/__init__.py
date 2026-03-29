"""OpenViper Admin Panel - Vue 3 style admin interface.

Provides a powerful, auto-generated administration interface for OpenViper models
with a Vue 3 SPA frontend.

Example:
    .. code-block:: python

        from openviper.admin import admin, ModelAdmin, register

        @register(Post)
        class PostAdmin(ModelAdmin):
            list_display = ["title", "author", "created_at"]
            list_filter = ["is_published", "author"]
            search_fields = ["title", "body"]

        # Or using decorator shorthand
        @admin.register(Post)
        class PostAdmin(ModelAdmin):
            list_display = ["title", "created_at"]
"""

from openviper.admin.actions import ActionResult, action
from openviper.admin.decorators import register
from openviper.admin.options import ChildTable, ModelAdmin
from openviper.admin.registry import AdminRegistry, admin
from openviper.admin.site import get_admin_site


def unregister(model_class: type) -> None:
    """Unregister a model from the admin site."""
    admin.unregister(model_class)


__all__ = [
    "admin",
    "AdminRegistry",
    "ModelAdmin",
    "register",
    "unregister",
    "get_admin_site",
    "action",
    "ActionResult",
    "ChildTable",
]
