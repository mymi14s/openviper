"""Low-level admin module import utilities.

Separated from ``discovery.py`` to avoid circular imports: this module
has zero dependency on ``registry.py``, so ``registry.py`` can safely
import from here at module level.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys

logger = logging.getLogger("openviper.admin")


def import_admin_module(app_name: str) -> bool:
    """Import the admin.py module from an app.

    Args:
        app_name: Dotted path to the app package.

    Returns:
        True if admin.py was found and imported, False otherwise.
    """
    admin_module_name = f"{app_name}.admin"

    if admin_module_name in sys.modules:
        logger.debug("Admin module %s already loaded", admin_module_name)
        return True

    try:
        spec = importlib.util.find_spec(admin_module_name)
        if spec is None:
            logger.debug("No admin.py found in %s", app_name)
            return False
    except (ModuleNotFoundError, ValueError) as e:
        logger.debug("Could not find admin module for %s: %s", app_name, e)
        return False

    try:
        importlib.import_module(admin_module_name)
        logger.debug("Imported admin.py from %s", app_name)
        return True
    except ImportError as e:
        logger.critical("Failed to import admin.py from %s: %s", app_name, e)
        raise
    except SyntaxError as e:
        logger.critical("Syntax error in admin.py from %s: %s", app_name, e)
        raise
    except Exception as e:
        logger.critical("Unexpected error importing %s: %s", admin_module_name, e)
        raise
