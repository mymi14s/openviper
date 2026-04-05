"""Auto-discovery of admin.py modules from installed apps.

Automatically imports admin.py from each app in INSTALLED_APPS,
triggering any @register decorators defined there.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from pathlib import Path

from openviper.admin.auth_admin import register_auth_models
from openviper.admin.registry import admin
from openviper.conf import settings

logger = logging.getLogger("openviper.admin")


def discover_admin_modules() -> list[str]:
    """Discover and import admin.py from all installed apps.

    Returns:
        List of app names where admin.py was successfully imported.
    """

    discovered = []
    installed_apps = getattr(settings, "INSTALLED_APPS", [])

    for app in installed_apps:
        if import_admin_module(app):
            discovered.append(app)

    return discovered


def import_admin_module(app_name: str) -> bool:
    """Import the admin.py module from an app.

    Args:
        app_name: Dotted path to the app package.

    Returns:
        True if admin.py was found and imported, False otherwise.
    """
    admin_module_name = f"{app_name}.admin"

    # Check if already imported
    if admin_module_name in sys.modules:
        logger.debug(f"Admin module {admin_module_name} already loaded")
        return True

    # Try to find the module
    try:
        spec = importlib.util.find_spec(admin_module_name)
        if spec is None:
            logger.debug(f"No admin.py found in {app_name}")
            return False
    except (ModuleNotFoundError, ValueError) as e:
        logger.debug(f"Could not find admin module for {app_name}: {e}")
        return False

    # Import the module
    try:
        importlib.import_module(admin_module_name)
        logger.debug(f"Imported admin.py from {app_name}")
        return True
    except ImportError as e:
        logger.warning(f"Error importing admin.py from {app_name}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error importing {admin_module_name}: {e}")
        return False


def discover_extensions() -> list[dict]:
    """Discover admin_extensions directories from all installed apps.

    Scans each app in INSTALLED_APPS for an ``admin_extensions/`` subdirectory
    and collects all ``.js`` files found there.

    Returns:
        List of dicts with keys ``app``, ``file``, ``url``, and ``path``.
    """

    extensions: list[dict] = []
    installed_apps = getattr(settings, "INSTALLED_APPS", [])

    for app_name in installed_apps:
        try:
            spec = importlib.util.find_spec(app_name)
            if spec is None or spec.origin is None:
                continue
            app_dir = Path(spec.origin).parent
            ext_dir = app_dir / "admin_extensions"
            if not ext_dir.is_dir():
                continue
            for ext_file in sorted(list(ext_dir.glob("*.js")) + list(ext_dir.glob("*.vue"))):
                file_type = "module" if ext_file.suffix == ".vue" else "script"
                extensions.append(
                    {
                        "app": app_name,
                        "file": ext_file.name,
                        "url": f"/admin/extensions/{app_name}/{ext_file.name}",
                        "path": str(ext_file),
                        "type": file_type,
                    }
                )
                logger.debug(f"Found admin extension: {app_name}/{ext_file.name} ({file_type})")
        except Exception as e:
            logger.debug(f"Error scanning extensions for {app_name}: {e}")

    return extensions


def autodiscover() -> None:
    """Run admin auto-discovery.

    This is called automatically when the admin app is initialized.
    It imports admin.py from all installed apps.
    """

    admin.auto_discover_from_installed_apps()

    # Register built-in auth models

    register_auth_models()
