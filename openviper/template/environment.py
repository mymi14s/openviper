"""Jinja2 environment factory with automatic plugin loading.

Constructs and caches :class:`~jinja2.SandboxedEnvironment` instances.
After construction, :mod:`~openviper.template.plugin_loader` registers
all configured filters and globals before the first template render.
"""

from __future__ import annotations

import functools
import logging
import os
from typing import TYPE_CHECKING, Any, cast

from openviper.conf import settings
from openviper.template import plugin_loader
from openviper.template.paths import PROJECT_ROOT, iter_app_dirs, validate_path_and_warn

jinja2_available: bool = False
SandboxedEnvironment: Any = None
FileSystemLoader: Any = None
select_autoescape: Any = None

try:
    from jinja2 import FileSystemLoader, select_autoescape
    from jinja2.sandbox import SandboxedEnvironment

    jinja2_available = True
except ImportError:
    pass

if TYPE_CHECKING:
    from jinja2.sandbox import SandboxedEnvironment as SandboxedEnvironmentType

logger = logging.getLogger("openviper.template.environment")


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
    if not jinja2_available:
        raise ImportError("jinja2 is required for template rendering")
    auto_reload = getattr(settings, "TEMPLATE_AUTO_RELOAD", True)
    env = cast(
        "SandboxedEnvironmentType",
        SandboxedEnvironment(
            loader=FileSystemLoader(list(search_paths)),
            autoescape=select_autoescape(enabled_extensions=("html", "jinja2"), default=True),
            auto_reload=auto_reload,
        ),
    )
    plugin_loader.load(env)
    return env


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
            validated = validate_path_and_warn(
                os.path.abspath(templates_dir), PROJECT_ROOT, "TEMPLATES_DIR"
            )
            if validated is not None and os.path.isdir(validated):
                paths.append(validated)

    for app_label, app_dir in iter_app_dirs():
        abs_path = os.path.abspath(os.path.join(app_dir, "templates"))
        validated = validate_path_and_warn(abs_path, PROJECT_ROOT, f"App {app_label!r} template")
        if validated is not None and os.path.isdir(validated) and validated not in paths:
            paths.append(validated)

    return tuple(paths)
