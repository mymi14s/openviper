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
from typing import Any

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError:
    Environment = None  # type: ignore[misc, assignment]
    FileSystemLoader = None  # type: ignore[misc, assignment]
    select_autoescape = None  # type: ignore[assignment]

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
    env = Environment(
        loader=FileSystemLoader(list(search_paths)),
        autoescape=select_autoescape(enabled_extensions=("html", "jinja2"), default=True),
    )
    plugin_loader.load(env)
    return env
