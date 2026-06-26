"""OpenViper Admin Panel - Vue 3 style admin interface."""

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
