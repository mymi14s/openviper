"""Jinja2 plugin auto-loader.

Discovers and registers filters and global functions from app-level
``<app_dir>/jinja_plugins/`` (lower priority) and project-level
``JINJA_PLUGINS["path"]`` (higher priority, overwrites app-level).

Runs exactly once per process (singleton guard).  Discovery can be
initiated in a background thread to avoid blocking the main thread.
Private names (starting with ``_``) and unsafe callables are always skipped.
"""

from __future__ import annotations

import atexit
import concurrent.futures
import importlib.util
import logging
import os
import sys
import threading
import types
from typing import TYPE_CHECKING

from openviper.conf import settings
from openviper.template.paths import PROJECT_ROOT, iter_app_dirs, validate_path_and_warn

if TYPE_CHECKING:
    from jinja2 import Environment

logger = logging.getLogger("openviper.template.plugin_loader")

UNSAFE_CALLABLE_NAMES: frozenset[str] = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "input",
        "breakpoint",
        "getattr",
        "hasattr",
        "type",
        "vars",
    }
)


class State:
    """Singleton state container for discovered plugins.

    Uses ``__init__`` to ensure each instance owns its own mutable
    collections, avoiding the shared-class-attribute bug that arises
    from class-level ``dict`` defaults.
    """

    def __init__(self) -> None:
        self.loaded: bool = False
        self.filters: dict[str, object] = {}
        self.globals: dict[str, object] = {}
        self.future: concurrent.futures.Future[bool] | None = None


STATE = State()
DISCOVERY_LOCK = threading.Lock()
THREAD_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="plugin-loader"
)
atexit.register(THREAD_POOL.shutdown, False)


def apply_to_env(env: Environment) -> None:
    """Copy cached filters and globals into a Jinja2 environment instance."""
    if STATE.filters:
        env.filters.update(STATE.filters.copy())
    if STATE.globals:
        env.globals.update(STATE.globals.copy())


def load(env: Environment, *, wait: bool = True) -> None:
    """Register discovered Jinja2 plugins into *env*.

    Safe to call multiple times; filesystem discovery runs exactly once.
    Subsequent calls re-apply the in-memory cache.  Project-level plugins
    overwrite app-level plugins that share the same name.

    Args:
        env: A :class:`jinja2.Environment` instance.
        wait: If True (default), blocks until discovery completes. If False,
            registers any already-discovered plugins immediately and returns.
    """
    if STATE.loaded:
        apply_to_env(env)
        return

    cfg: dict[str, object] = getattr(settings, "JINJA_PLUGINS", None) or {}
    if not cfg.get("enable", False):
        STATE.loaded = True
        return

    with DISCOVERY_LOCK:
        if STATE.loaded:
            apply_to_env(env)
            return

        if STATE.future is None:
            STATE.future = THREAD_POOL.submit(discover_plugins, cfg)

        if wait:
            try:
                STATE.future.result(timeout=30.0)
            except concurrent.futures.TimeoutError:
                logger.warning("Plugin discovery timed out after 30 seconds")
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning("Plugin discovery failed: %s", exc)

        apply_to_env(env)

        if STATE.future is None or STATE.future.done():
            STATE.loaded = True


def scan_plugin_dirs(root: str) -> dict[str, dict[str, object]]:
    """Scan filters/ and globals/ subdirectories under *root*.

    Returns a mapping with ``"filters"`` and ``"globals"`` keys whose
    values are the respective callable dictionaries discovered by
    :func:`scan_directory`.
    """
    result: dict[str, dict[str, object]] = {
        "filters": scan_directory(os.path.join(root, "filters")),
        "globals": scan_directory(os.path.join(root, "globals")),
    }
    return result


def merge_scanned(
    root: str,
    merged_filters: dict[str, object],
    merged_globals: dict[str, object],
) -> None:
    """Scan plugin directories under *root* and merge into target dicts."""
    scanned = scan_plugin_dirs(root)
    merged_filters.update(scanned["filters"])
    merged_globals.update(scanned["globals"])


def log_registered(kind: str, collection: dict[str, object]) -> None:
    """Log the count and sorted names of a registered plugin collection."""
    if collection:
        logger.debug(
            "Registered %d Jinja2 %s(s): %s",
            len(collection),
            kind,
            sorted(collection),
        )


def discover_plugins(cfg: dict[str, object]) -> bool:
    """Discover and merge plugins from app-level and project-level roots.

    Returns True on success, False on failure.
    """
    merged_filters: dict[str, object] = {}
    merged_globals: dict[str, object] = {}

    for _app_label, app_dir in iter_app_dirs():
        app_plugin_root = os.path.join(app_dir, "jinja_plugins")
        if not os.path.isdir(app_plugin_root):
            continue
        merge_scanned(app_plugin_root, merged_filters, merged_globals)

    plugin_root: str = str(cfg.get("path", "jinja_plugins") or "jinja_plugins")
    if not os.path.isabs(plugin_root):
        validated = validate_path_and_warn(
            os.path.abspath(plugin_root), PROJECT_ROOT, "JINJA_PLUGINS"
        )
        plugin_root = "" if validated is None else validated
    if plugin_root and os.path.isdir(plugin_root):
        merge_scanned(plugin_root, merged_filters, merged_globals)
    elif plugin_root:
        logger.debug(
            "JINJA_PLUGINS path %r does not exist; skipping project-level plugin discovery.",
            plugin_root,
        )

    STATE.filters.update(merged_filters)
    STATE.globals.update(merged_globals)

    log_registered("filter", STATE.filters)
    log_registered("global", STATE.globals)

    return True


def reset() -> None:
    """Reset the singleton state.

    For testing only. Calling this in production code will cause plugins
    to be re-discovered on the next ``load()`` call.
    """
    STATE.loaded = False
    STATE.filters.clear()
    STATE.globals.clear()
    STATE.future = None


def scan_directory(directory: str) -> dict[str, object]:
    """Return ``{callable_name: callable}`` for all public callables found.

    Uses :func:`os.scandir` for a single-level, non-recursive scan.
    Files whose names start with ``_`` (e.g. ``__init__.py``) or that do not
    end with ``.py`` are silently skipped.
    """
    callables: dict[str, object] = {}

    if not os.path.isdir(directory):
        return callables

    try:
        scanner = os.scandir(directory)
    except OSError as exc:
        logger.warning("Cannot scan plugin directory %r: %s", directory, exc)
        return callables

    with scanner:
        for entry in scanner:
            if not entry.is_file(follow_symlinks=False):
                continue
            try:
                if entry.is_symlink():
                    continue
            except OSError:
                continue
            fname = entry.name
            if fname.startswith("_") or not fname.endswith(".py"):
                continue
            module_name = fname[:-3]
            module = import_plugin_module(entry.path, module_name)
            if module is None:
                continue
            for attr in dir(module):
                if attr.startswith("_") or attr in UNSAFE_CALLABLE_NAMES:
                    continue
                obj = getattr(module, attr, None)
                if callable(obj):
                    callables[attr] = obj

    return callables


def import_plugin_module(path: str, name: str) -> types.ModuleType | None:
    """Load a Python source file directly from *path* via :mod:`importlib`.

    Returns ``None`` and logs a warning if loading fails.  Bytecode writing
    is suppressed for the duration of the load to avoid writing transient
    ``.pyc`` files to ``__pycache__`` for dynamically discovered plugin
    modules.
    """
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            logger.warning("Could not create module spec for %r", path)
            return None
        module = importlib.util.module_from_spec(spec)
        prev_dont_write = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            spec.loader.exec_module(module)
        finally:
            sys.dont_write_bytecode = prev_dont_write
        return module
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("Failed to import Jinja2 plugin %r: %s", path, exc)
        return None
