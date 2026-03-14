"""Admin decorators for model registration.

Provides the @register decorator for registering models with the admin site.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from openviper.admin.registry import admin

if TYPE_CHECKING:
    from openviper.admin.options import ModelAdmin
    from openviper.db.models import Model


def register(
    *models: type[Model],
) -> Callable[[type[ModelAdmin]], type[ModelAdmin]]:
    """Decorator to register one or more models with the admin site.

    Can register multiple models with the same ModelAdmin class.

    Args:
        *models: One or more model classes to register.

    Returns:
        A decorator that registers the ModelAdmin class.

    Example:
        .. code-block:: python

            @register(Post)
            class PostAdmin(ModelAdmin):
                list_display = ["title", "created_at"]

            # Multiple models with same admin
            @register(Post, Article)
            class ContentAdmin(ModelAdmin):
                list_display = ["title"]
    """

    def decorator(admin_class: type[ModelAdmin]) -> type[ModelAdmin]:
        for model in models:
            admin.register(model, admin_class)
        return admin_class

    return decorator
