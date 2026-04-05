"""Model event dispatcher for OpenViper.

Allows per-model lifecycle event hooks to be declared in project settings via
``MODEL_EVENTS`` and automatically fired from :class:`~openviper.db.models.Model`
``save()`` / ``delete()`` calls.

The dispatcher is active whenever ``MODEL_EVENTS`` is configured in settings.

Settings
--------
::

    MODEL_EVENTS = {
        "blog.models.Post": {
            "before_validate": ["blog.events.sanitise_post"],
            "before_save":     ["blog.events.stamp_updated_at"],
            "after_insert":    ["blog.events.create_likes"],
            "on_change":       ["blog.events.reindex_post"],
            "after_delete":    ["blog.events.cleanup_comments"],
        },
        "blog.models.Comment": {
            "after_insert": ["blog.events.notify_post_author"],
        },
    }

Model paths are matched against ``"{module}.{ClassName}"`` of the model
instance.  Handler dotted-paths are resolved once at dispatcher
construction time, so runtime dispatch is a pair of O(1) dict lookups.

Supported event names
---------------------
All nine ``Model`` lifecycle hooks are supported.

**save() — create flow** (``pk is None``):

``before_validate``
    Fired before field validation on INSERT.
``validate``
    Fired after built-in field validation passes on INSERT.
``before_insert``
    Fired after validation, before the INSERT (create only).
``before_save``
    Fired immediately before the DB write (both create and update).
``after_insert``
    Fired after a successful INSERT (create only).
``on_change``
    Fired after INSERT (all fields treated as changed) or after UPDATE
    when at least one field value actually changed.

**save() — update flow** (``pk`` set):

``before_validate``
    Fired before field validation on UPDATE.
``validate``
    Fired after built-in field validation passes on UPDATE.
``before_save``
    Fired immediately before the UPDATE.
``on_update``
    Fired after a successful UPDATE (update only).
``on_change``
    Fired after UPDATE when at least one field value changed.

**delete() flow**:

``on_delete``
    Fired before the DELETE is issued.  Raising here aborts the deletion.
``after_delete``
    Fired after a successful DELETE.

Handler signature
-----------------
Handlers receive the model instance as their first positional argument,
the triggering event name as the ``event`` keyword argument, and any
extra keyword arguments forwarded via ``trigger()``::

    def create_likes(post, event: str | None = None) -> None:
        init_like_counter.send(post_id=post.pk)

Handlers are called synchronously (inline with the DB operation) and
exceptions are caught and logged so a misbehaving handler never interrupts
model persistence or other handlers in the same event.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import threading
from collections.abc import Callable
from typing import Any, cast

# Module-level reference so tests can patch ``openviper.db.events.settings``
# without having to reach into ``openviper.conf.settings``.
from openviper.conf.settings import settings

logger = logging.getLogger("openviper.db")

# Sentinel for "not yet initialised" — avoids confusing None (disabled) with
# "not yet set".
_UNSET: Any = object()
_init_lock = threading.Lock()

# Module-level dispatcher cache.  _UNSET = never built; None = built but disabled.
_dispatcher_cache: Any = _UNSET

# Background task tracking to prevent garbage collection and log exceptions.
_background_tasks: set[asyncio.Task[Any]] = set()
_MAX_BACKGROUND_TASKS: int = 1024

# Populated by @model_event.trigger(...).  Keyed by model_path → event_name
# → list of callables.  Intentionally separate from the settings-based
# dispatcher so that decorator-registered handlers fire even when
# MODEL_EVENTS is empty.
_decorator_registry: dict[str, dict[str, list[Any]]] = {}
_dec_registry_lock = threading.Lock()

# All Model lifecycle hook names that the dispatcher understands.
SUPPORTED_EVENTS: frozenset[str] = frozenset(
    {
        # save() — validation (create + update)
        "before_validate",
        "validate",
        # save() — pre-write (create + update)
        "before_insert",  # create only
        "before_save",
        # save() — post-write (create + update)
        "after_insert",  # create only
        "on_update",  # update only
        "on_change",  # create (all fields) or update (changed fields only)
        # delete()
        "on_delete",
        "after_delete",
        # bulk operations (Manager.bulk_create / Manager.bulk_update)
        "pre_bulk_create",
        "post_bulk_create",
        "pre_bulk_update",
        "post_bulk_update",
    }
)


class ModelEventDispatcher:
    """Registry of per-model event → handler callables.

    Handlers are resolved from dotted-path strings at construction time and
    stored as ``{model_path: {event_name: [callable, ...]}}``.  Runtime
    dispatch is two O(1) dict lookups — no import overhead.

    The instance is immutable after ``__init__``, so concurrent reads require
    no locking.
    """

    __slots__ = ("_handlers",)

    def __init__(self, config: dict[str, Any]) -> None:
        """Build the dispatcher from a MODEL_EVENTS config dict.

        Args:
            config: Mapping of model path → {event_name → [dotted_callable]}.
                    Unknown event names are accepted but generate a debug log.
        """
        handlers: dict[str, dict[str, list[Any]]] = {}

        for model_path, events in config.items():
            if not isinstance(events, dict):
                logger.warning(
                    "MODEL_EVENTS[%r]: expected a dict of events, got %r — skipped.",
                    model_path,
                    type(events).__name__,
                )
                continue

            resolved: dict[str, list[Any]] = {}
            for event_name, dotted_paths in events.items():
                if event_name not in SUPPORTED_EVENTS:
                    logger.debug(
                        "MODEL_EVENTS[%r][%r]: unknown event name; supported: %s.",
                        model_path,
                        event_name,
                        ", ".join(sorted(SUPPORTED_EVENTS)),
                    )
                callables: list[Any] = []
                for path in dotted_paths:
                    fn = _resolve_dotted(path)
                    if fn is not None:
                        callables.append(fn)
                if callables:
                    resolved[event_name] = callables

            if resolved:
                handlers[model_path] = resolved

        # Freeze into a plain dict for minimal attribute-access overhead.
        self._handlers: dict[str, dict[str, list[Any]]] = handlers

    # ------------------------------------------------------------------

    def trigger(
        self,
        model_path: str,
        event_name: str,
        instance: Any,
        **kwargs: Any,
    ) -> None:
        """Dispatch *event_name* to all handlers registered for *model_path*.

        Each handler is called with ``(instance, event=event_name, **kwargs)``.
        Exceptions are caught per-handler and logged; they never propagate to
        the caller.

        Args:
            model_path: Dotted ``"module.ClassName"`` key (e.g. ``"blog.models.Post"``).
            event_name: Event to dispatch (``"after_insert"``, ``"on_change"``,
                        ``"after_delete"``).
            instance:   The model instance that triggered the event.
            **kwargs:   Extra context forwarded verbatim to every handler.
        """
        # Dispatch settings-based handlers (MODEL_EVENTS).
        event_map = self._handlers.get(model_path)
        if event_map:
            handlers = event_map.get(event_name)
            if handlers:
                for handler in handlers:
                    try:
                        _call_handler(handler, instance, event_name, **kwargs)
                    except Exception as exc:
                        qualname = getattr(handler, "__qualname__", None) or repr(handler)
                        logger.warning(
                            "MODEL_EVENTS handler %r raised for %s.%s: %s",
                            qualname,
                            model_path,
                            event_name,
                            exc,
                        )

        # Dispatch decorator-registered handlers (from @model_event.trigger).
        _dispatch_decorator_handlers(model_path, event_name, instance, **kwargs)

    def __bool__(self) -> bool:
        return bool(self._handlers)

    def __repr__(self) -> str:
        return (
            f"<ModelEventDispatcher "
            f"models={list(self._handlers)} "
            f"handlers={sum(len(v) for v in self._handlers.values())}>"
        )


def get_dispatcher() -> ModelEventDispatcher | None:
    """Return the active :class:`ModelEventDispatcher`, or ``None``.

    The dispatcher is initialised lazily on the first call and cached in a
    module-level variable.  Concurrent calls are serialised by ``_init_lock``
    with a lock-free fast path.

    Returns:
        An empty (falsy) :class:`ModelEventDispatcher` when ``MODEL_EVENTS``
        is empty or no handlers can be resolved.
    """
    global _dispatcher_cache
    # Fast path (lock-free): already built (None or a dispatcher).
    if _dispatcher_cache is not _UNSET:
        return cast("ModelEventDispatcher | None", _dispatcher_cache)

    with _init_lock:
        # Double-check after acquiring the lock.
        if _dispatcher_cache is not _UNSET:
            return cast("ModelEventDispatcher | None", _dispatcher_cache)

        _dispatcher_cache = _build_dispatcher()
        return cast("ModelEventDispatcher | None", _dispatcher_cache)


def reset_dispatcher() -> None:
    """Clear the cached dispatcher singleton.

    Call in test teardown (e.g. ``autouse`` fixture) to ensure every test
    case builds a fresh dispatcher from the settings that are active at that
    moment.
    """
    global _dispatcher_cache
    _dispatcher_cache = _UNSET


def _build_dispatcher() -> ModelEventDispatcher | None:
    """Create and return a dispatcher from current settings, or ``None``."""
    try:
        model_events: dict[str, Any] = dict(getattr(settings, "MODEL_EVENTS", {}) or {})
        dispatcher = ModelEventDispatcher(model_events)

        return dispatcher

    except Exception as exc:
        logger.warning("MODEL_EVENTS: could not build dispatcher: %s", exc)
        return None


# Allowed root module prefixes for MODEL_EVENTS handler imports.
# Only these namespaces are permitted — everything else is rejected.
_ALLOWED_MODULE_PREFIXES: frozenset[str] = frozenset(("openviper",))


def _is_safe_module_path(module_path: str) -> bool:
    """Validate that a module path is safe to import.

    Uses an allowlist approach: only modules under explicitly trusted
    namespaces are permitted.  Project app modules are auto-detected
    from INSTALLED_APPS.

    Allows:
    - OpenViper modules (openviper.*)
    - Modules whose root package appears in INSTALLED_APPS

    Blocks:
    - Everything else (including system modules like os, subprocess, etc.)
    """
    root_module = module_path.split(".")[0]

    # Always allow openviper internals
    if root_module in _ALLOWED_MODULE_PREFIXES:
        return True

    # Allow project apps registered in INSTALLED_APPS
    installed = getattr(settings, "INSTALLED_APPS", ())
    for app in installed:
        app_root = app.split(".")[0]
        if root_module == app_root:
            return True

    return False


def _resolve_dotted(path: str | Callable[..., Any]) -> Any | None:
    """Import and return the callable at *path* (``"pkg.module.attr"``).

    If *path* is already a callable, returns it as-is.

    Returns ``None`` and logs a warning on any resolution failure so a
    misconfigured handler path never crashes the worker or web server.

    Security: Validates module path against a blocklist of dangerous
    system modules to prevent arbitrary code execution if settings are
    compromised.
    """
    if callable(path):
        return path

    if "." not in path:
        logger.warning(
            "MODEL_EVENTS: invalid handler path %r — must be a dotted string "
            "like 'myapp.events.my_handler'.",
            path,
        )
        return None

    module_path, _, attr = path.rpartition(".")

    # prevent importing dangerous system modules
    if not _is_safe_module_path(module_path):
        logger.error(
            "MODEL_EVENTS: blocked attempt to import dangerous module %r. "
            "Handler path %r is not allowed for security reasons.",
            module_path,
            path,
        )
        return None

    try:
        module = importlib.import_module(module_path)
        return getattr(module, attr)
    except (ImportError, AttributeError) as exc:
        logger.warning(
            "MODEL_EVENTS: could not resolve handler %r: %s",
            path,
            exc,
        )
        return None


def _call_handler(handler: Any, instance: Any, event_name: str, **kwargs: Any) -> None:
    """Invoke *handler* for both sync and async callables.

    Async handlers are scheduled as tasks on the running event loop (which
    always exists inside ``Model.save()`` / ``Model.delete()``).  Sync
    handlers are called directly.

    Background tasks are tracked to prevent premature garbage collection
    and to log any unhandled exceptions.
    """
    if inspect.iscoroutinefunction(handler):
        if len(_background_tasks) >= _MAX_BACKGROUND_TASKS:
            logger.warning(
                "MODEL_EVENTS: background task limit (%d) reached — "
                "skipping async handler %r for %s.",
                _MAX_BACKGROUND_TASKS,
                getattr(handler, "__qualname__", repr(handler)),
                event_name,
            )
            return
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(handler(instance, event=event_name, **kwargs))
            # Track task to prevent garbage collection
            _background_tasks.add(task)
            # Clean up when done and log any exceptions
            task.add_done_callback(_task_done_callback)
        except RuntimeError:
            logger.warning(
                "MODEL_EVENTS: async handler %r skipped — no running event loop.",
                getattr(handler, "__qualname__", repr(handler)),
            )
    else:
        handler(instance, event=event_name, **kwargs)


def _task_done_callback(task: asyncio.Task[Any]) -> None:
    """Clean up completed background task and log exceptions."""
    _background_tasks.discard(task)
    try:
        # Retrieve exception if any (prevents "Task exception was never retrieved" warnings)
        exc = task.exception()
        if exc is not None:
            logger.exception(
                "MODEL_EVENTS: unhandled exception in async handler",
                exc_info=exc,
            )
    except asyncio.CancelledError:
        pass  # Task was cancelled, ignore


def _dispatch_decorator_handlers(
    model_path: str,
    event_name: str,
    instance: Any,
    **kwargs: Any,
) -> None:
    """Fire all handlers registered via ``@model_event.trigger(...)`` for
    *model_path* / *event_name*.

    Called both from :meth:`ModelEventDispatcher.trigger` (settings on) and
    directly from ``Model._trigger_event`` (settings off), so decorator
    handlers always fire.
    """
    event_map = _decorator_registry.get(model_path)
    if not event_map:
        return
    handlers = event_map.get(event_name)
    if not handlers:
        return
    for handler in handlers:
        try:
            _call_handler(handler, instance, event_name, **kwargs)
        except Exception as exc:
            logger.warning(
                "@model_event handler %r raised for %s.%s: %s",
                getattr(handler, "__qualname__", repr(handler)),
                model_path,
                event_name,
                exc,
            )


class _ModelEventProxy:
    """Exposes ``@model_event.trigger(...)`` as a decorator factory.

    Register an inline handler for a model lifecycle event without adding an
    entry to ``MODEL_EVENTS`` in ``settings.py``::

        from openviper.db.events import model_event

        @model_event.trigger("posts.models.Post.after_insert")
        async def send_welcome_email(post, *, event):
            from posts.tasks import email_new_post
            email_new_post.send(post_id=post.pk)

    The dotted path passed to ``trigger`` must use the form
    ``"{module}.{ClassName}.{event_name}"``.  The last segment is the event
    name; everything before it is the model key (matching ``MODEL_EVENTS``).

    Decorator-registered handlers fire even when ``MODEL_EVENTS`` is empty.
    """

    __slots__ = ()

    def trigger(self, model_event_path: str) -> Any:
        """Return a decorator that registers *fn* for *model_event_path*.

        Args:
            model_event_path: Dotted path of the form
                ``"{module}.{ClassName}.{event_name}"``, e.g.
                ``"posts.models.Post.after_insert"``.  The final segment is
                the event name; the remainder is the model key.

        Returns:
            A pass-through decorator that registers the function and returns
            it unchanged, so the function can still be called directly.

        Raises:
            ValueError: If *model_event_path* contains no dot (cannot be
                split into model path + event name).
        """
        if "." not in model_event_path:
            raise ValueError(
                "@model_event.trigger requires a dotted path of the form "
                "'myapp.models.MyModel.event_name', "
                f"got {model_event_path!r}."
            )
        model_path, _, event_name = model_event_path.rpartition(".")

        def decorator(fn: Any) -> Any:
            with _dec_registry_lock:
                model_events = _decorator_registry.setdefault(model_path, {})
                model_events.setdefault(event_name, []).append(fn)
            return fn

        return decorator

    def __getattr__(self, name: str) -> Any:
        if name in SUPPORTED_EVENTS:
            return self._make_shortcut_decorator(name)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute {name!r}")

    def _make_shortcut_decorator(self, event_name: str) -> Callable[[str], Any]:
        def decorator_factory(model_path: str) -> Any:
            def decorator(fn: Any) -> Any:
                with _dec_registry_lock:
                    model_events = _decorator_registry.setdefault(model_path, {})
                    model_events.setdefault(event_name, []).append(fn)
                return fn

            return decorator

        return decorator_factory


#: Singleton proxy for decorator-based model event registration.
#: See :class:`_ModelEventProxy` for usage.
model_event: _ModelEventProxy = _ModelEventProxy()
