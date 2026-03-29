"""Jinja2 plugin auto-loader.

Discovers and registers filters and global functions from:

1. **App-level** ``<app_dir>/jinja_plugins/`` for each app in
   ``settings.INSTALLED_APPS`` (lower priority).
2. **Project-level** ``<plugin_root>/`` configured via ``JINJA_PLUGINS``
   (higher priority — overwrites app-level plugins with the same name).

The loader runs exactly **once** per process (singleton guard) and caches
all discovered plugins in memory, so template rendering incurs zero
filesystem or import overhead after startup.

Plugin discovery can be initiated in a background thread to avoid blocking
the main thread during initial import.

Directory layout under each plugin root::

    jinja_plugins/
        filters/
            slugify.py      # def slugify(value): ...
            truncate.py     # def truncate(value, length): ...
        globals/
            now.py          # def now(): ...

Configuration in *settings* (``JINJA_PLUGINS``)::

    JINJA_PLUGINS = {
        "enable": 1,         # 0/False → loader does not run
        "path": "jinja_plugins",   # project-relative path (default: "jinja_plugins")
    }

Each callable in a module is registered under its own name as either a
Jinja2 filter (``env.filters``) or a global (``env.globals``).  Private
names (starting with ``_``) are always skipped.
"""

from __future__ import annotations

import atexit
import concurrent.futures
import importlib
import importlib.util
import logging
import os
import sys
import threading
from typing import Any

from openviper.conf import settings

logger = logging.getLogger("openviper.template.plugin_loader")

# Callable names that must never be exposed to templates, regardless of source.
_UNSAFE_CALLABLE_NAMES: frozenset[str] = frozenset(
    {"eval", "exec", "compile", "__import__", "open", "input", "breakpoint"}
)


class _State:
    loaded: bool = False
    filters: dict[str, Any] = {}
    globals: dict[str, Any] = {}
    future: concurrent.futures.Future[bool] | None = None


_STATE = _State()
_DISCOVERY_LOCK = threading.Lock()
_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="plugin-loader"
)
atexit.register(_THREAD_POOL.shutdown, False)


def load(env: Any, *, wait: bool = True) -> None:
    """Register discovered Jinja2 plugins into *env*.

    Safe to call multiple times; filesystem discovery runs exactly once.
    Subsequent calls re-apply the in-memory cache to the given environment
    (which may differ from the one used on first call when the LRU cache
    produces multiple ``Environment`` instances for different search-path
    tuples).

    Discovery order (lower index = lower priority):

    1. App-level ``<app_dir>/jinja_plugins/`` for each entry in
       ``settings.INSTALLED_APPS``.
    2. Project-level directory from ``JINJA_PLUGINS["path"]``.

    Project-level plugins overwrite app-level plugins that share the same name.

    Args:
        env: A :class:`jinja2.Environment` instance.
        wait: If True (default), blocks until discovery completes. If False,
            registers any already-discovered plugins immediately and returns.
    """
    if _STATE.loaded:
        # Fast path: apply from cache only — no I/O, no imports.
        if _STATE.filters:
            env.filters.update(_STATE.filters.copy())
        if _STATE.globals:
            env.globals.update(_STATE.globals.copy())
        return

    cfg: dict[str, Any] = getattr(settings, "JINJA_PLUGINS", None) or {}
    if not cfg.get("enable", False):
        _STATE.loaded = True
        return

    with _DISCOVERY_LOCK:
        # Double-check after acquiring lock
        if _STATE.loaded:
            if _STATE.filters:
                env.filters.update(_STATE.filters.copy())
            if _STATE.globals:
                env.globals.update(_STATE.globals.copy())
            return

        # Start discovery in background if not already started
        if _STATE.future is None:
            _STATE.future = _THREAD_POOL.submit(_discover_plugins, cfg)

        # Wait for discovery if requested
        if wait:
            try:
                _STATE.future.result(timeout=30.0)  # 30 second timeout
            except concurrent.futures.TimeoutError:
                logger.warning("Plugin discovery timed out after 30 seconds")
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning("Plugin discovery failed: %s", exc)

        # Apply discovered plugins
        if _STATE.filters:
            env.filters.update(_STATE.filters.copy())
        if _STATE.globals:
            env.globals.update(_STATE.globals.copy())

        _STATE.loaded = True


def _discover_plugins(cfg: dict[str, Any]) -> bool:
    """Internal function to discover plugins in background thread.

    Returns True on success, False on failure.
    """
    merged_filters: dict[str, Any] = {}
    merged_globals: dict[str, Any] = {}

    # 1. App-level discovery (lower priority — project-level overwrites).
    for app_label in getattr(settings, "INSTALLED_APPS", ()):
        try:
            mod = importlib.import_module(app_label)
            if not (hasattr(mod, "__file__") and mod.__file__):
                continue
            app_plugin_root = os.path.join(os.path.dirname(mod.__file__), "jinja_plugins")
            if not os.path.isdir(app_plugin_root):
                continue
            merged_filters.update(_scan_directory(os.path.join(app_plugin_root, "filters")))
            merged_globals.update(_scan_directory(os.path.join(app_plugin_root, "globals")))
        except ImportError, AttributeError:
            continue

    # 2. Project-level discovery (higher priority — overwrites app-level).
    plugin_root: str = cfg.get("path", "jinja_plugins") or "jinja_plugins"
    # Guard against relative path traversal (e.g. "../../etc").  Absolute paths
    # supplied by the operator are permitted as-is.
    if not os.path.isabs(plugin_root):
        project_root = os.path.abspath(".")
        resolved_root = os.path.abspath(plugin_root)
        if not (resolved_root == project_root or resolved_root.startswith(project_root + os.sep)):
            logger.warning(
                "JINJA_PLUGINS path %r escapes project root; "
                "skipping project-level plugin discovery.",
                plugin_root,
            )
            plugin_root = ""  # sentinel — skip the elif/else below
    if plugin_root and os.path.isdir(plugin_root):
        merged_filters.update(_scan_directory(os.path.join(plugin_root, "filters")))
        merged_globals.update(_scan_directory(os.path.join(plugin_root, "globals")))
    elif plugin_root:
        logger.debug(
            "JINJA_PLUGINS path %r does not exist; skipping project-level plugin discovery.",
            plugin_root,
        )

    _STATE.filters.update(merged_filters)
    _STATE.globals.update(merged_globals)

    if _STATE.filters:
        logger.debug(
            "Registered %d Jinja2 filter(s): %s",
            len(_STATE.filters),
            sorted(_STATE.filters),
        )
    if _STATE.globals:
        logger.debug(
            "Registered %d Jinja2 global(s): %s",
            len(_STATE.globals),
            sorted(_STATE.globals),
        )

    return True


def reset() -> None:
    """Reset the singleton state.

    **For testing only.** Calling this in production code will cause plugins
    to be re-discovered on the next ``load()`` call.
    """
    _STATE.loaded = False
    _STATE.filters.clear()
    _STATE.globals.clear()
    _STATE.future = None


def _scan_directory(directory: str) -> dict[str, Any]:
    """Return ``{callable_name: callable}`` for all public callables found.

    Uses :func:`os.scandir` for a single-level, non-recursive scan.
    Files whose names start with ``_`` (e.g. ``__init__.py``) or that do not
    end with ``.py`` are silently skipped.
    """
    callables: dict[str, Any] = {}

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
                # Skips __pycache__, sub-directories, symlinks to dirs, etc.
                continue
            fname = entry.name
            if fname.startswith("_") or not fname.endswith(".py"):
                continue
            module_name = fname[:-3]
            module = _import_module(entry.path, module_name)
            if module is None:
                continue
            for attr in dir(module):
                if attr.startswith("_") or attr in _UNSAFE_CALLABLE_NAMES:
                    continue
                obj = getattr(module, attr, None)
                if callable(obj):
                    callables[attr] = obj

    return callables


def _import_module(path: str, name: str) -> Any:
    """Load a Python source file directly from *path* via :mod:`importlib`.

    Returns ``None`` and logs a warning if loading fails.

    Bytecode writing is suppressed for the duration of the load to avoid
    leaving unclosed SQLite connections in Python's ``__pycache__`` store.
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
