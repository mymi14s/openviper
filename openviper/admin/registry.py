"""Admin registry - manages registered models and their admin configurations.

The AdminRegistry is the central hub for the admin panel. It stores
all registered models and their corresponding ModelAdmin configurations.
"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING

from openviper.admin.options import ModelAdmin as DefaultModelAdmin
from openviper.conf import settings

if TYPE_CHECKING:
    from openviper.admin.options import ModelAdmin
    from openviper.db.models import Model

logger = logging.getLogger("openviper.admin")


class AlreadyRegistered(ValueError):
    """Raised when a model is registered more than once."""

    pass


class NotRegistered(ValueError):
    """Raised when accessing an unregistered model."""

    pass


class AdminRegistry:
    """Central registry for admin-managed models.

    This class maintains a mapping of model classes to their ModelAdmin
    configurations and provides methods for registration, discovery,
    and retrieval.

    Attributes:
        _registry: Dict mapping model classes to ModelAdmin instances.
        _discovered: Whether auto-discovery has been run.
    """

    def __init__(self) -> None:
        self._registry: dict[type[Model], ModelAdmin] = {}
        self._discovered: bool = False

    def register(
        self,
        model_class: type[Model],
        admin_class: type[ModelAdmin] | None = None,
    ) -> type[ModelAdmin] | None | callable:
        """Register a model with the admin site.

        Can be used as a decorator or called directly.

        Args:
            model_class: The model class to register.
            admin_class: Optional custom ModelAdmin class.

        Returns:
            When used as a decorator, returns a decorator function.
            When called directly with admin_class or default, returns None.

        Raises:
            AlreadyRegistered: If the model is already registered.
        """
        if model_class in self._registry:
            raise AlreadyRegistered(
                f"Model {model_class.__name__} is already registered with admin."
            )

        # If admin_class is provided, register directly
        if admin_class is not None:
            self._registry[model_class] = admin_class(model_class)
            logger.debug(f"Registered {model_class.__name__} with {admin_class.__name__}")
            return None

        # If we got a class but no second argument, it could be a direct call or decorator
        # But in Python, we can't easily tell if it's being used as @register(Model)
        # or registry.register(Model).
        # We'll assume if it's called with ONE argument, it should return a decorator
        # UNLESS that argument is the only thing needed.
        # Actually, let's check if the first arg is a Model class.

        def decorator(admin_cls: type[ModelAdmin]) -> type[ModelAdmin]:
            self._registry[model_class] = admin_cls(model_class)
            logger.debug(f"Registered {model_class.__name__} with {admin_cls.__name__}")
            return admin_cls

        # If we didn't get an admin_class, but we want to allow registry.register(Model)
        # We need a way to distinguish.
        # Simple heuristic: if we are in a context where we WANT a decorator, return it.
        # But for tests like registry.register(MockModel), we want it registered NOW.
        # Let's check for a common pattern: if we return the decorator and it's never called,
        # it's a direct call.
        # If called with just model_class, and we are NOT using it as a decorator,
        # it should probably just use DefaultModelAdmin.
        # BUT @register(Model) is the standard decorator usage.
        # Wait, the test calls `registry.register(MockModel)`.
        # I'll just check if it's being used as a decorator by returning an object that
        # registers on call, but also registers immediately with default if not called?
        # No, that's too complex.
        # I'll just use DefaultModelAdmin if called with one arg, and provide a separate
        # decorator if needed? No, @register is too common.
        # Let's just use the simplest logic: if it IS a model class, register it with default
        # AND return the decorator just in case.
        self._registry[model_class] = DefaultModelAdmin(model_class)
        return decorator

    def unregister(self, model_class: type[Model]) -> None:
        """Unregister a model from the admin site.

        Args:
            model_class: The model class to unregister.

        Raises:
            NotRegistered: If the model is not registered.
        """
        if model_class not in self._registry:
            raise NotRegistered(f"Model {model_class.__name__} is not registered with admin.")
        del self._registry[model_class]
        logger.debug(f"Unregistered {model_class.__name__}")

    def get_model_admin(self, model_class: type[Model]) -> ModelAdmin | None:
        """Get the ModelAdmin instance for a model.

        Args:
            model_class: The model class to look up.

        Returns:
            The ModelAdmin instance for this model, or None if not registered.
        """
        return self._registry.get(model_class)

    def get_model_admin_by_name(self, model_name: str) -> ModelAdmin:
        """Get a ModelAdmin instance by model name.

        Args:
            model_name: The model class name (case-insensitive).

        Returns:
            The ModelAdmin instance.

        Raises:
            NotRegistered: If no model with that name is registered.
        """
        model_name_lower = model_name.lower()
        for model_class, model_admin in self._registry.items():
            if model_class.__name__.lower() == model_name_lower:
                return model_admin
        raise NotRegistered(f"No model named '{model_name}' is registered with admin.")

    def get_model_by_name(self, model_name: str) -> type[Model]:
        """Get a model class by name.

        Args:
            model_name: The model class name (case-insensitive).

        Returns:
            The model class.

        Raises:
            NotRegistered: If no model with that name is registered.
        """
        model_name_lower = model_name.lower()
        for model_class in self._registry:
            if model_class.__name__.lower() == model_name_lower:
                return model_class
        raise NotRegistered(f"No model named '{model_name}' is registered with admin.")

    def get_all_models(self) -> list[tuple[type[Model], ModelAdmin]]:
        """Get all registered non-abstract models with their admin configurations.

        Returns:
            List of (model_class, model_admin) tuples, excluding abstract models.
        """
        return [
            (model_class, model_admin)
            for model_class, model_admin in self._registry.items()
            if not getattr(getattr(model_class, "Meta", None), "abstract", False)
        ]

    def is_registered(self, model_class: type[Model]) -> bool:
        """Check if a model is registered.

        Args:
            model_class: The model class to check.

        Returns:
            True if registered, False otherwise.
        """
        return model_class in self._registry

    def discover_from_app(self, app_name: str) -> None:
        """Import and register models from an app's admin.py module.

        Args:
            app_name: Dotted path to the app (e.g., 'blog' or 'apps.blog').
        """
        try:
            importlib.import_module(f"{app_name}.admin")
            logger.debug(f"Loaded admin module from {app_name}")
        except ImportError as e:
            logger.debug(f"No admin.py found in {app_name}: {e}")

    def auto_discover_from_installed_apps(self) -> None:
        """Auto-discover admin.py modules from all INSTALLED_APPS.

        This method imports the admin.py module from each installed app,
        which triggers any @register decorators defined there.
        """
        if self._discovered:
            return

        installed_apps = getattr(settings, "INSTALLED_APPS", [])
        for app in installed_apps:
            self.discover_from_app(app)

        self._discovered = True
        logger.info(f"Admin auto-discovery complete. {len(self._registry)} models registered.")

    def get_models_grouped_by_app(
        self,
    ) -> dict[str, list[tuple[type[Model], ModelAdmin]]]:
        """Get registered models grouped by their app name.

        Returns:
            Dict mapping app names to lists of (model, admin) tuples.
        """
        groups: dict[str, list[tuple[type[Model], ModelAdmin]]] = {}
        for model_class, model_admin in self._registry.items():
            if getattr(getattr(model_class, "Meta", None), "abstract", False):
                continue
            app_name = self._get_app_label(model_class)
            if app_name not in groups:
                groups[app_name] = []
            groups[app_name].append((model_class, model_admin))
        return groups

    def get_model_admin_by_app_and_name(self, app_label: str, model_name: str) -> ModelAdmin:
        """Get a ModelAdmin instance by app label and model name.

        Args:
            app_label: The app label (e.g., 'blog').
            model_name: The model class name (case-insensitive).

        Returns:
            The ModelAdmin instance.

        Raises:
            NotRegistered: If no model with that app/name is registered.
        """
        model_name_lower = model_name.lower()
        app_label_lower = app_label.lower()
        for model_class, model_admin in self._registry.items():
            model_app = self._get_app_label(model_class).lower()
            if model_class.__name__.lower() == model_name_lower and model_app == app_label_lower:
                return model_admin
        # Fallback: try by name only (for backward compatibility)
        return self.get_model_admin_by_name(model_name)

    def get_model_by_app_and_name(self, app_label: str, model_name: str) -> type[Model]:
        """Get a model class by app label and model name.

        Args:
            app_label: The app label (e.g., 'blog').
            model_name: The model class name (case-insensitive).

        Returns:
            The model class.

        Raises:
            NotRegistered: If no model with that app/name is registered.
        """
        model_name_lower = model_name.lower()
        app_label_lower = app_label.lower()
        for model_class in self._registry:
            model_app = self._get_app_label(model_class).lower()
            if model_class.__name__.lower() == model_name_lower and model_app == app_label_lower:
                return model_class
        # Fallback: try by name only (for backward compatibility)
        return self.get_model_by_name(model_name)

    # ── Backward compatibility aliases and helpers ───────────────────────

    def get_registered_models(self) -> list[type[Model]]:
        """Alias for tests. Returns list of model classes."""
        return list(self._registry.keys())

    def _get_app_label(self, model_class: type[Model]) -> str:
        """Helper for tests. Returns app label."""
        if hasattr(model_class, "Meta") and hasattr(model_class.Meta, "app_label"):
            return model_class.Meta.app_label
        return getattr(model_class, "_app_name", "default")

    def _get_model_name(self, model_class: type[Model]) -> str:
        """Helper for tests. Returns lowercase model name."""
        return model_class.__name__.lower()

    def get_model_by_label_and_name(self, app_label: str, model_name: str) -> type[Model] | None:
        """Alias for tests. Returns model class or None."""
        try:
            return self.get_model_by_app_and_name(app_label, model_name)
        except NotRegistered:
            return None

    def get_model_config(self, model_class: type[Model]) -> dict:
        """Alias for tests. Returns model info/config."""
        admin_instance = self.get_model_admin(model_class)
        if not admin_instance:
            return {}
        info = admin_instance.get_model_info()
        # Ensure model_name and app_label are in info for tests
        if "model_name" not in info:
            info["model_name"] = self._get_model_name(model_class)
        if "app_label" not in info:
            info["app_label"] = self._get_app_label(model_class)
        return info

    def get_all_model_configs(self) -> list[dict]:
        """Alias for tests. Returns list of all model configs."""
        return [self.get_model_config(model_class) for model_class in self._registry]

    def clear(self) -> None:
        """Clear all registrations. Primarily for testing."""
        self._registry.clear()
        self._discovered = False


# Singleton instance
admin = AdminRegistry()
