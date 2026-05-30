"""Jinja2 environment factory with automatic plugin loading.

Constructs and caches :class:`~jinja2.SandboxedEnvironment` instances.
After construction, :mod:`~openviper.template.plugin_loader` registers
all configured filters and globals before the first template render.
"""

from __future__ import annotations

import functools
import importlib
import logging
import os
from typing import TYPE_CHECKING, Any, cast

from openviper.conf import settings
from openviper.template import plugin_loader

_jinja2_available: bool = False
_SandboxedEnvironment: Any = None
_FileSystemLoader: Any = None
_select_autoescape: Any = None

try:
    from jinja2 import FileSystemLoader as _FileSystemLoader
    from jinja2 import select_autoescape as _select_autoescape
    from jinja2.sandbox import SandboxedEnvironment as _SandboxedEnvironment

    _jinja2_available = True
except ImportError:
    pass

if TYPE_CHECKING:
    from jinja2.sandbox import SandboxedEnvironment as SandboxedEnvironmentType

logger = logging.getLogger("openviper.template.environment")


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


@functools.lru_cache(maxsize=16)
def get_jinja2_env(search_paths: tuple[str, ...]) -> SandboxedEnvironmentType:
    """Return a cached Jinja2 :class:`~jinja2.SandboxedEnvironment` for *search_paths*.

    On the first call for a given path tuple, the environment is constructed
    and :func:`~openviper.template.plugin_loader.load` registers all
    configured filters and globals.  Subsequent calls with the same tuple
    return the same cached object.

    Uses :class:`~jinja2.SandboxedEnvironment` to prevent template authors
    from accessing dangerous attributes (``__class__``, ``__subclasses__``,
    etc.) and executing arbitrary Python code.

    Args:
        search_paths: Tuple of template directory paths (must be hashable
            for use as an LRU-cache key).

    Raises:
        ImportError: If ``jinja2`` is not installed.
    """
    if not _jinja2_available:
        raise ImportError("jinja2 is required for template rendering")
    auto_reload = getattr(settings, "TEMPLATE_AUTO_RELOAD", True)
    env = cast(
        "SandboxedEnvironmentType",
        _SandboxedEnvironment(
            loader=_FileSystemLoader(list(search_paths)),
            autoescape=_select_autoescape(enabled_extensions=("html", "jinja2"), default=True),
            auto_reload=auto_reload,
        ),
    )
    plugin_loader.load(env)
    return env


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


def get_template_directories() -> tuple[str, ...]:
    """Return a deduplicated tuple of absolute paths to template directories.

    Scans ``settings.INSTALLED_APPS`` for ``templates/`` folders and includes
    the project-level ``settings.TEMPLATES_DIR``.  All resolved paths are
    validated against the project root to prevent directory-traversal attacks.
    """
    paths: list[str] = []

    if settings.TEMPLATES_DIR:
        templates_dir = settings.TEMPLATES_DIR
        if isinstance(templates_dir, str):
            project_templates = os.path.abspath(templates_dir)
            validated = validate_path_within_root(project_templates, PROJECT_ROOT)
            if validated is not None and os.path.isdir(validated):
                paths.append(validated)
            elif validated is None:
                logger.warning(
                    "TEMPLATES_DIR %r escapes project root; skipping.",
                    templates_dir,
                )

    installed_apps: tuple[str, ...] | list[str] = cast(
        "tuple[str, ...] | list[str]", settings.INSTALLED_APPS
    )
    for app_label in installed_apps:
        try:
            mod = importlib.import_module(app_label)
            if not (hasattr(mod, "__file__") and mod.__file__):
                continue
            app_templates = os.path.join(os.path.dirname(mod.__file__), "templates")
            abs_path = os.path.abspath(app_templates)
            validated = validate_path_within_root(abs_path, PROJECT_ROOT)
            if validated is not None and os.path.isdir(validated):
                if validated not in paths:
                    paths.append(validated)
            elif validated is None:
                logger.warning(
                    "App %r template path %r escapes project root; skipping.",
                    app_label,
                    abs_path,
                )
        except ImportError:
            continue

    return tuple(paths)
