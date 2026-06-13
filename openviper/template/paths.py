"""Shared path-resolution utilities for the template subsystem.

Provides directory-traversal guards and app-directory discovery used
by both :mod:`~openviper.template.environment` and
:mod:`~openviper.template.plugin_loader`.
"""

from __future__ import annotations

import importlib
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

from openviper.conf import settings

logger = logging.getLogger("openviper.template.paths")


def resolve_project_root() -> str:
    """Return the absolute path to the project root directory.

    Walks up from the settings module to find a stable root.  Falls back to
    the current working directory when a settings module path is unavailable.
    """
    settings_module = os.environ.get("OPENVIPER_SETTINGS_MODULE", "")
    if settings_module:
        try:
            mod = importlib.import_module(settings_module)
            if hasattr(mod, "__file__") and mod.__file__:
                return os.path.dirname(os.path.abspath(mod.__file__))
        except ImportError:
            pass
    return os.path.abspath(".")


PROJECT_ROOT: str = resolve_project_root()


def validate_path_within_root(path: str, root: str) -> str | None:
    """Resolve *path* and return it only if it resides within *root*.

    Neutralises directory-traversal tokens (``../``), encoded slashes, and
    double-decoding edge cases per the path-normalization security matrix.
    Returns ``None`` when the resolved path escapes *root*.
    """
    resolved = os.path.realpath(path)
    root_resolved = os.path.realpath(root)
    if resolved == root_resolved or resolved.startswith(root_resolved + os.sep):
        return resolved
    return None


def validate_path_and_warn(path: str, root: str, label: str) -> str | None:
    """Validate *path* resides within *root*, logging a warning on escape.

    Delegates to :func:`validate_path_within_root` for the security check.
    When the path escapes *root*, logs a warning using *label* to identify
    the source and returns ``None``.  Otherwise returns the resolved path.
    """
    validated = validate_path_within_root(path, root)
    if validated is None:
        logger.warning("%s path %r escapes project root; skipping.", label, path)
    return validated


def get_app_dir(app_label: str) -> str | None:
    """Return the filesystem directory for an installed app, or ``None``.

    Imports *app_label* as a Python module, resolves its ``__file__``
    attribute, and returns ``os.path.dirname`` of that path.  Returns
    ``None`` when the module cannot be imported, lacks ``__file__``, or
    raises ``AttributeError``.
    """
    try:
        mod = importlib.import_module(app_label)
    except ImportError, AttributeError:
        return None
    if not (hasattr(mod, "__file__") and mod.__file__):
        return None
    return os.path.dirname(mod.__file__)


def iter_app_dirs() -> Iterator[tuple[str, str]]:
    """Yield ``(app_label, app_dir)`` for each resolvable installed app.

    Iterates ``settings.INSTALLED_APPS``, resolves each to its filesystem
    directory via :func:`get_app_dir`, and skips entries that return
    ``None``.
    """
    for app_label in getattr(settings, "INSTALLED_APPS", ()):
        app_dir = get_app_dir(app_label)
        if app_dir is not None:
            yield app_label, app_dir
