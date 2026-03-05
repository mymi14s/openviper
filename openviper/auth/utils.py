"""Authentication and authorization utilities."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
from typing import cast

logger = logging.getLogger("openviper.auth")


def get_user_model() -> type:
    """Return the User model class.

    Returns the default User model or a custom one if USER_MODEL
    (or legacy AUTH_USER_MODEL) is defined in settings.
    """
    from openviper.conf import settings

    custom_user = getattr(settings, "USER_MODEL", getattr(settings, "AUTH_USER_MODEL", None))
    if custom_user:
        try:
            from openviper.utils import import_string

            return cast(type, import_string(custom_user))
        except (ImportError, AttributeError):
            pass

    from openviper.auth.models import User

    return User


def discover_models() -> None:
    """Import models.py from all installed apps to ensure they are registered."""
    from openviper.conf import settings
    from openviper.core.app_resolver import AppResolver

    installed_apps = getattr(settings, "INSTALLED_APPS", [])
    resolver = AppResolver()

    for app_name in installed_apps:
        # Try importing {app_name}.models
        try:
            importlib.import_module(f"{app_name}.models")
            logger.debug("Imported models from %s", app_name)
        except ImportError:
            # If direct import fails, try resolving path (might be a local app)
            app_path, found = resolver.resolve_app(app_name)
            if found and app_path:
                models_file = os.path.join(app_path, "models.py")
                if os.path.exists(models_file):
                    try:
                        spec = importlib.util.spec_from_file_location(
                            f"{app_name}.models", models_file
                        )
                        if spec and spec.loader:
                            module = importlib.util.module_from_spec(spec)
                            spec.loader.exec_module(module)
                            logger.debug("Imported models from file %s", models_file)
                    except Exception as e:
                        logger.warning("Failed to import models from %s: %s", models_file, e)


async def sync_content_types() -> None:
    """Synchronize ContentType records with all registered models.

    Creates records for new models and removes records for models that
    no longer exist.
    """
    # First, ensure all models are discovered/imported
    discover_models()

    from openviper.auth.models import ContentType
    from openviper.db.models import ModelMeta

    # Get all non-abstract models from registry
    all_models = list(ModelMeta.registry.values())

    # Get existing content types from DB
    try:
        existing_cts = await ContentType.objects.all()  # type: ignore[misc]
    except Exception as e:
        # Table might not exist yet during first migration
        logger.debug("Could not fetch existing ContentTypes: %s", e)
        return

    existing_map = {(ct.app_label, ct.model): ct for ct in existing_cts}

    current_keys = set()
    newly_created = 0
    deleted_count = 0

    for model_cls in all_models:
        app_label = model_cls._app_name  # type: ignore[attr-defined]
        model_name = model_cls._model_name  # type: ignore[attr-defined]

        # Skip the base Model placeholder
        if app_label == "default" and model_name == "Model":
            continue

        key = (app_label, model_name)
        current_keys.add(key)

        if key not in existing_map:
            await ContentType.objects.create(app_label=app_label, model=model_name)
            newly_created += 1

    # Clean up stale content types
    for key, ct in existing_map.items():
        if key not in current_keys:
            await ct.delete()
            deleted_count += 1

    if newly_created > 0 or deleted_count > 0:
        logger.info(
            "ContentType synchronization: created %d, deleted %d",
            newly_created,
            deleted_count,
        )
