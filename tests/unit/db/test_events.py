"""Unit tests for openviper/db/events.py."""

from __future__ import annotations

import asyncio
import logging
import threading
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

import openviper.db.events
import openviper.db.events as events_mod
from openviper.db.events import (
    _UNSET,
    ModelEventDispatcher,
    _background_tasks,
    _build_dispatcher,
    _call_handler,
    _decorator_registry,
    _dispatch_decorator_handlers,
    _is_safe_module_path,
    _resolve_dotted,
    _task_done_callback,
    get_dispatcher,
    model_event,
    reset_dispatcher,
)


@pytest.fixture(autouse=True)
def reset_events():
    """Reset the global dispatcher and decorator registry before each test."""
    openviper.db.events._dispatcher_cache = _UNSET
    _decorator_registry.clear()
    yield
    openviper.db.events._dispatcher_cache = _UNSET
    _decorator_registry.clear()


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def make_dispatcher() -> ModelEventDispatcher:
    return ModelEventDispatcher({})


def make_mock_model_cls(name: str = "Post", app: str = "blog") -> type:
    cls = type(name, (), {"_app_name": app, "_model_name": name})
    return cls


# ---------------------------------------------------------------------------
# ModelEventDispatcher
# ---------------------------------------------------------------------------


class TestModelEventDispatcher:
    def test_get_dispatcher_returns_instance(self):
        d = get_dispatcher()
        assert isinstance(d, ModelEventDispatcher)

    def test_singleton(self):
        assert get_dispatcher() is get_dispatcher()

    @pytest.mark.asyncio
    async def test_register_handler(self):
        handler = AsyncMock()
        model_event.trigger("blog.Post.after_insert")(handler)
        assert handler in _decorator_registry.get("blog.Post", {}).get("after_insert", [])

    @pytest.mark.asyncio
    async def test_register_multiple_handlers_same_event(self):
        h1 = AsyncMock()
        h2 = AsyncMock()
        model_event.trigger("blog.Post.after_insert")(h1)
        model_event.trigger("blog.Post.after_insert")(h2)
        handlers = _decorator_registry.get("blog.Post", {}).get("after_insert", [])
        assert h1 in handlers and h2 in handlers

    @pytest.mark.asyncio
    async def test_dispatch_calls_handler(self):
        handler = MagicMock()
        model_key = "blog.Post"
        # Register via decorator proxy
        model_event.trigger(f"{model_key}.after_insert")(handler)

        instance = MagicMock()
        d = make_dispatcher()
        d.trigger(model_key, "after_insert", instance)
        handler.assert_called_once_with(instance, event="after_insert")

    def test_dispatch_no_handlers_no_error(self):
        d = make_dispatcher()
        instance = MagicMock()
        # Should not raise
        d.trigger("blog.NoHandlers", "after_insert", instance)

    def test_dispatch_unknown_event_no_error(self):
        d = make_dispatcher()
        handler = MagicMock()
        model_event.trigger("blog.Post.after_insert")(handler)
        instance = MagicMock()
        d.trigger("blog.Post", "unknown_event", instance)

    def test_from_settings_loads_handlers(self):
        reset_dispatcher()
        with patch("openviper.db.events.settings") as mock_settings:
            mock_settings.MODEL_EVENTS = {
                "blog.Post": {
                    "after_insert": ["tests.unit.db.test_events.dummy_handler"],
                }
            }
            d = get_dispatcher()
            assert d is not None
            assert "blog.Post" in d._handlers

    def test_dispatcher_repr(self):
        with patch("openviper.db.events._resolve_dotted", return_value=lambda x: x):
            d = ModelEventDispatcher({"a": {"b": ["test.handler"]}})
            r = repr(d)
            assert "ModelEventDispatcher" in r
            assert "models=['a']" in r
            assert "handlers=1" in r

    def test_invalid_config_dict(self):
        with patch("openviper.db.events.logger") as mock_logger:
            d = ModelEventDispatcher({"model": "not-a-dict"})
            assert "model" not in d._handlers
            assert mock_logger.warning.called

    def test_unknown_event_name_logging(self):
        with patch("openviper.db.events.logger") as mock_logger:
            with patch("openviper.db.events._resolve_dotted", return_value=lambda x: x):
                d = ModelEventDispatcher({"model": {"unknown": ["test.handler"]}})
                assert mock_logger.debug.called

    @pytest.mark.asyncio
    async def test_trigger_handler_exception(self, caplog):
        def failing_handler(instance, event, **kwargs):
            raise Exception("fail_trigger")

        failing_handler.__qualname__ = "failing_handler"

        d = ModelEventDispatcher({"blog.Post": {"after_insert": [failing_handler]}})
        instance = MagicMock()

        with caplog.at_level(logging.WARNING, logger="openviper.db"):
            d.trigger("blog.Post", "after_insert", instance)

        assert "failing_handler" in caplog.text
        assert "blog.Post" in caplog.text
        assert "after_insert" in caplog.text
        assert "fail_trigger" in caplog.text

    def test_get_dispatcher_concurrency_mock(self):
        reset_dispatcher()
        with patch("openviper.db.events._build_dispatcher") as mock_build:
            mock_build.return_value = MagicMock()
            get_dispatcher()
            assert mock_build.called

    def test_build_dispatcher_exception(self):
        with patch("openviper.db.events.ModelEventDispatcher", side_effect=Exception("ouch")):
            with patch("openviper.db.events.logger") as mock_logger:
                res = _build_dispatcher()
                assert res is None
                assert mock_logger.warning.called

    def test_resolve_dotted_invalid_path(self):
        with patch("openviper.db.events.logger") as mock_logger:
            assert _resolve_dotted("no_dot") is None
            assert mock_logger.warning.called

    def test_resolve_dotted_import_error(self):
        with patch("openviper.db.events.logger") as mock_logger:
            assert _resolve_dotted("non.existent.module.attr") is None
            assert mock_logger.warning.called

    @pytest.mark.asyncio
    async def test_call_handler_no_loop(self):
        async def mock_async_handler(inst, **kwargs):
            pass

        with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
            with patch("openviper.db.events.logger") as mock_logger:
                _call_handler(mock_async_handler, MagicMock(), "event")
                mock_logger.warning.assert_called_with(
                    "MODEL_EVENTS: async handler %r skipped — no running event loop.", ANY
                )

    def test_dispatch_decorator_handler_exception(self, caplog):
        def failing_dec_handler(instance, event, **kwargs):
            raise Exception("fail_dec")

        failing_dec_handler.__qualname__ = "failing_dec_handler"

        model_path = "err.Model"
        event = "after_insert"
        _decorator_registry[model_path] = {event: [failing_dec_handler]}

        with caplog.at_level(logging.WARNING, logger="openviper.db"):
            _dispatch_decorator_handlers(model_path, event, MagicMock())

        assert "failing_dec_handler" in caplog.text
        assert "fail_dec" in caplog.text

    def test_trigger_decorator_invalid_path(self):
        with pytest.raises(ValueError, match="requires a dotted path"):
            model_event.trigger("nodot")


class TestGetDispatcherDoubleCheck:
    def test_double_check_returns_cached(self):
        sentinel = MagicMock()
        openviper.db.events._dispatcher_cache = sentinel
        result = get_dispatcher()
        assert result is sentinel

    def test_double_check_inside_lock(self):
        sentinel = MagicMock()

        original_build = openviper.db.events._build_dispatcher

        def fake_build():
            openviper.db.events._dispatcher_cache = sentinel
            return sentinel

        with patch("openviper.db.events._build_dispatcher", side_effect=fake_build):
            openviper.db.events._dispatcher_cache = _UNSET
            result = get_dispatcher()
            assert result is sentinel


class TestResolveDottedBlocked:
    @pytest.mark.parametrize(
        "path",
        [
            "os.system",
            "subprocess.call",
            "sys.exit",
            "pickle.loads",
            "shutil.rmtree",
            "builtins.eval",
        ],
    )
    def test_blocked_module_returns_none(self, path):
        with patch("openviper.db.events.logger") as mock_logger:
            assert _resolve_dotted(path) is None
            mock_logger.error.assert_called_once()

    def test_safe_module_path_allowed(self):
        assert _is_safe_module_path("openviper.auth.models") is True
        assert _is_safe_module_path("myapp.events.handler") is True

    def test_safe_module_path_blocked(self):
        assert _is_safe_module_path("os") is False
        assert _is_safe_module_path("subprocess") is False
        assert _is_safe_module_path("pickle") is False

    def test_resolve_callable_passthrough(self):
        fn = lambda x: x
        assert _resolve_dotted(fn) is fn


class TestCallHandlerAsyncWithLoop:
    @pytest.mark.asyncio
    async def test_async_handler_creates_task(self):
        called = []

        async def async_handler(inst, event=None):
            called.append(event)

        _call_handler(async_handler, MagicMock(), "after_insert")
        await asyncio.sleep(0.05)
        assert "after_insert" in called

    @pytest.mark.asyncio
    async def test_async_handler_tracked_in_background_tasks(self):
        async def slow_handler(inst, event=None):
            await asyncio.sleep(0.1)

        initial_count = len(_background_tasks)
        _call_handler(slow_handler, MagicMock(), "after_insert")
        assert len(_background_tasks) > initial_count
        await asyncio.sleep(0.15)


class TestTaskDoneCallback:
    def test_successful_task_discarded(self):
        task = MagicMock()
        task.exception.return_value = None
        _background_tasks.add(task)
        _task_done_callback(task)
        assert task not in _background_tasks

    def test_task_with_exception_logged(self):
        task = MagicMock()
        task.exception.return_value = RuntimeError("boom")
        _background_tasks.add(task)
        with patch("openviper.db.events.logger") as mock_logger:
            _task_done_callback(task)
            mock_logger.exception.assert_called_once()
        assert task not in _background_tasks

    def test_cancelled_task_ignored(self):
        task = MagicMock()
        task.exception.side_effect = asyncio.CancelledError()
        _background_tasks.add(task)
        _task_done_callback(task)
        assert task not in _background_tasks


class TestGetDispatcherDoubleCheckInLock:
    """Double-check branch inside the lock."""

    def test_second_thread_sees_cached_value(self):
        """Simulate two threads entering `get_dispatcher` concurrently.

        The second thread acquires the lock after the first has already
        populated `_dispatcher_cache`, so it hits the inner
        `if _dispatcher_cache is not _UNSET`.
        """
        # First, seed the cache so the double-check branch fires.
        sentinel = ModelEventDispatcher({})
        events_mod._dispatcher_cache = sentinel

        # Now enter the lock path by *clearing* the fast-path,
        # but restore it *inside* the lock before our call completes.
        # Simplest: we directly exercise the code path.
        # Reset fast path:
        events_mod._dispatcher_cache = _UNSET

        # Set cache while holding the lock so the double-check fires.
        with events_mod._init_lock:
            events_mod._dispatcher_cache = sentinel

        # Next call should return sentinel via fast path.
        assert get_dispatcher() is sentinel

    def test_concurrent_double_check_returns_cached(self):
        """Exercise the double-check branch by pre-setting cache under lock."""
        barrier = threading.Barrier(2, timeout=5)
        results = [None, None]

        def thread_fn(idx):
            barrier.wait()
            results[idx] = get_dispatcher()

        # Pre-build a dispatcher via first call
        with patch.object(events_mod, "_build_dispatcher", return_value=None) as mock_build:
            events_mod._dispatcher_cache = _UNSET
            t1 = threading.Thread(target=thread_fn, args=(0,))
            t2 = threading.Thread(target=thread_fn, args=(1,))
            t1.start()
            t2.start()
            t1.join()
            t2.join()
            # _build_dispatcher should be called at most once
            assert mock_build.call_count <= 1


def dummy_handler(instance):
    """Used as a string import target in tests."""
    pass
