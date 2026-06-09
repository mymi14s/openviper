"""Scan ``settings.INSTALLED_APPS`` for ``tasks.py`` modules on worker startup.

Imports each app's ``tasks`` submodule when it exists, triggering
``@actor`` / ``@periodic`` registration via decorator side-effects.
"""

from __future__ import annotations

import importlib

from openviper.tasks.logging import get_task_logger
from openviper.tasks.registry import Registry

logger = get_task_logger("openviper.tasks.discovery")


def discover_tasks(installed_apps: tuple[str, ...] | list[str]) -> None:
    """Import ``tasks.py`` submodules for each app in *installed_apps*.

    Silently ignores ``ModuleNotFoundError`` for apps without a
    ``tasks.py``.
    """
    registry = Registry()
    for app_label in installed_apps:
        if registry.is_discovered(app_label):
            continue
        registry.mark_discovered(app_label)

        module_name = f"{app_label}.tasks"
        try:
            importlib.import_module(module_name)
            print(f"Discovered tasks module: {module_name}")
        except ModuleNotFoundError:
            logger.debug("No tasks module for %s - skipping", app_label)
        except Exception:
            logger.exception("Error importing %s", module_name)
