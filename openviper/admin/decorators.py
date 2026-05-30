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

    Args:
        *models: One or more model classes to register.

    Returns:
        A decorator that registers the ModelAdmin class.
    """

    def decorator(admin_class: type[ModelAdmin]) -> type[ModelAdmin]:
        for model in models:
            admin.register(model, admin_class)
        return admin_class

    return decorator
