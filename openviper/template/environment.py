"""Jinja2 environment factory with automatic plugin loading.

This module is the single authoritative source for creating and caching
Jinja2 :class:`~jinja2.Environment` instances.  After constructing a new
environment the :mod:`~openviper.template.plugin_loader` is invoked so that
all custom filters and global functions are available before the first
template is rendered.

Usage::

    from openviper.template.environment import get_jinja2_env

    env = get_jinja2_env(("templates/", "blog/templates/"))
    html = env.get_template("index.html").render(user=user)
"""

from __future__ import annotations

import functools
import importlib
import os
from typing import Any

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError:
    Environment = None  # type: ignore[misc, assignment]
    FileSystemLoader = None  # type: ignore[misc, assignment]
    select_autoescape = None  # type: ignore[assignment]

from openviper.conf import settings
from openviper.template import plugin_loader


@functools.lru_cache(maxsize=16)
def get_jinja2_env(search_paths: tuple[str, ...]) -> Any:
    """Return a cached Jinja2 :class:`~jinja2.Environment` for *search_paths*.

    On the **first call** for a given path tuple the environment is
    constructed and :func:`~openviper.template.plugin_loader.load` registers
    all configured filters and globals.  Subsequent calls with the same tuple
    return the same cached object — no filesystem I/O, no re-import, zero
    overhead.

    Args:
        search_paths: Tuple of template directory paths (must be a tuple so
            it is hashable and usable as an LRU-cache key).

    Raises:
        ImportError: If ``jinja2`` is not installed.
    """
    if Environment is None:
        raise ImportError("jinja2 is required for template rendering")
    auto_reload = getattr(settings, "TEMPLATE_AUTO_RELOAD", True)
    env = Environment(
        loader=FileSystemLoader(list(search_paths)),
        autoescape=select_autoescape(enabled_extensions=("html", "jinja2"), default=True),
        auto_reload=auto_reload,
    )
    plugin_loader.load(env)
    return env


def get_template_directories() -> tuple[str, ...]:
    """Return a deduplicated tuple of absolute paths to template directories.

    Scans ``settings.INSTALLED_APPS`` for ``templates/`` folders and includes
    the project-level ``settings.TEMPLATES_DIR``.
    """
    paths: list[str] = []

    # 1. Project-level
    if settings.TEMPLATES_DIR:
        project_templates = os.path.abspath(settings.TEMPLATES_DIR)
        if os.path.isdir(project_templates):
            paths.append(project_templates)

    # 2. App-level
    for app_label in settings.INSTALLED_APPS:
        try:
            mod = importlib.import_module(app_label)
            if not (hasattr(mod, "__file__") and mod.__file__):
                continue
            app_templates = os.path.join(os.path.dirname(mod.__file__), "templates")
            if os.path.isdir(app_templates):
                abs_path = os.path.abspath(app_templates)
                if abs_path not in paths:
                    paths.append(abs_path)
        except ImportError:
            continue

    return tuple(paths)
