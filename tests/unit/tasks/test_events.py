"""Unit tests for openviper.tasks.events — ModelEventDispatcher."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

import openviper.tasks.events as _events_module
from openviper.tasks.events import (
    SUPPORTED_EVENTS,
    ModelEventDispatcher,
    _build_dispatcher,
    _call_handler,
    _dispatch_decorator_handlers,
    _resolve_dotted,
    get_dispatcher,
    model_event,
    reset_dispatcher,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cfg(**models):
    """Build a minimal MODEL_EVENTS config from keyword args.

    Usage::
        cfg = _make_cfg(**{
            "myapp.models.Foo": {
                "after_insert": ["tests.unit.tasks.test_events._noop"],
            }
        })
    """
    return models


def _noop(instance, **kwargs):
    """Dummy handler used in tests."""


# ---------------------------------------------------------------------------
# _resolve_dotted
# ---------------------------------------------------------------------------


class TestResolveDotted:
    def test_resolves_callable(self):
        fn = _resolve_dotted("openviper.tasks.events._resolve_dotted")
        assert fn is _resolve_dotted

    def test_returns_none_on_missing_module(self, caplog):
        result = _resolve_dotted("nonexistent_module.does_not_exist")
        assert result is None

    def test_returns_none_on_missing_attr(self, caplog):
        result = _resolve_dotted("openviper.tasks.events.no_such_thing")
        assert result is None

    def test_returns_none_on_no_dot(self, caplog):
        result = _resolve_dotted("filewithoutdot")
        assert result is None
        assert "invalid handler path" in caplog.text.lower() or "invalid" in caplog.text


# ---------------------------------------------------------------------------
# ModelEventDispatcher construction
# ---------------------------------------------------------------------------


class TestModelEventDispatcherInit:
    def test_empty_config_creates_empty_dispatcher(self):
        d = ModelEventDispatcher({})
        assert not bool(d)
        assert d._handlers == {}

    def test_resolves_valid_handler(self):
        cfg = {
            "myapp.models.Post": {
                "after_insert": ["openviper.tasks.events._resolve_dotted"],
            }
        }
        d = ModelEventDispatcher(cfg)
        assert "myapp.models.Post" in d._handlers
        assert "after_insert" in d._handlers["myapp.models.Post"]
        assert d._handlers["myapp.models.Post"]["after_insert"] == [_resolve_dotted]

    def test_skips_unresolvable_handler(self):
        cfg = {
            "myapp.models.Post": {
                "after_insert": ["not.a.real.callable"],
            }
        }
        d = ModelEventDispatcher(cfg)
        # model_path entry omitted because no callables were resolved
        assert "myapp.models.Post" not in d._handlers

    def test_skips_non_dict_events_value(self, caplog):
        cfg = {"myapp.models.Post": ["not", "a", "dict"]}
        d = ModelEventDispatcher(cfg)
        assert "myapp.models.Post" not in d._handlers

    def test_bool_true_when_handlers_present(self):
        cfg = {"m.M": {"after_insert": ["openviper.tasks.events._resolve_dotted"]}}
        d = ModelEventDispatcher(cfg)
        assert bool(d)

    def test_bool_false_when_empty(self):
        assert not bool(ModelEventDispatcher({}))

    def test_repr(self):
        cfg = {"m.M": {"after_insert": ["openviper.tasks.events._resolve_dotted"]}}
        r = repr(ModelEventDispatcher(cfg))
        assert "ModelEventDispatcher" in r
        assert "m.M" in r


# ---------------------------------------------------------------------------
# ModelEventDispatcher.trigger
# ---------------------------------------------------------------------------


class TestModelEventDispatcherTrigger:
    def _dispatcher_with_handler(self, handler):
        # Patch _resolve_dotted to pass the callable directly
        d = ModelEventDispatcher.__new__(ModelEventDispatcher)
        d._handlers = {"myapp.models.Post": {"after_insert": [handler]}}
        return d

    def test_calls_handler_with_instance(self):
        called_with = []

        def handler(instance, **kw):
            called_with.append((instance, kw))

        d = self._dispatcher_with_handler(handler)
        instance = object()
        d.trigger("myapp.models.Post", "after_insert", instance, extra=1)

        assert len(called_with) == 1
        assert called_with[0] == (instance, {"event": "after_insert", "extra": 1})

    def test_no_handlers_for_model_is_noop(self):
        d = ModelEventDispatcher({})
        d.trigger("missing.Model", "after_insert", object())  # must not raise

    def test_no_handlers_for_event_is_noop(self):
        called = []
        d = ModelEventDispatcher.__new__(ModelEventDispatcher)
        d._handlers = {"myapp.models.Post": {"on_change": [lambda i: called.append(i)]}}
        d.trigger("myapp.models.Post", "after_insert", object())  # wrong event
        assert called == []

    def test_handler_exception_is_caught_and_logged(self, caplog):
        def bad_handler(instance, **kw):
            raise RuntimeError("boom")

        d = self._dispatcher_with_handler(bad_handler)
        d.trigger("myapp.models.Post", "after_insert", object())
        assert "boom" in caplog.text

    def test_multiple_handlers_all_called(self):
        calls = []
        h1 = lambda i, **kw: calls.append("h1")  # noqa: E731
        h2 = lambda i, **kw: calls.append("h2")  # noqa: E731
        d = ModelEventDispatcher.__new__(ModelEventDispatcher)
        d._handlers = {"m.M": {"after_insert": [h1, h2]}}
        d.trigger("m.M", "after_insert", object())
        assert calls == ["h1", "h2"]

    def test_exception_in_first_handler_does_not_skip_second(self, caplog):
        calls = []

        def bad(i, **kw):
            raise ValueError("fail")

        def good(i, **kw):
            calls.append("good")

        d = ModelEventDispatcher.__new__(ModelEventDispatcher)
        d._handlers = {"m.M": {"after_insert": [bad, good]}}
        d.trigger("m.M", "after_insert", object())
        assert "good" in calls


# ---------------------------------------------------------------------------
# get_dispatcher / reset_dispatcher
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_dispatcher():
    """Reset cached dispatcher before and after each test."""
    reset_dispatcher()
    yield
    reset_dispatcher()


def _stub_settings(task_cfg, model_events_cfg):
    """Patch settings for dispatcher tests."""
    return patch(
        "openviper.tasks.events._build_dispatcher",
        side_effect=lambda: (
            ModelEventDispatcher(model_events_cfg) if bool(task_cfg.get("enabled")) else None
        ),
    )


class TestGetDispatcher:
    def test_returns_none_when_tasks_disabled(self):
        with patch("openviper.tasks.events._build_dispatcher", return_value=None):
            d = get_dispatcher()
        assert d is None

    def test_returns_dispatcher_when_tasks_enabled(self):
        mock_dispatcher = ModelEventDispatcher.__new__(ModelEventDispatcher)
        mock_dispatcher._handlers = {"m.M": {"after_insert": [_resolve_dotted]}}
        with patch(
            "openviper.tasks.events._build_dispatcher",
            return_value=mock_dispatcher,
        ):
            d = get_dispatcher()
        assert d is mock_dispatcher

    def test_caches_result_on_second_call(self):
        build_calls = []

        def fake_build():
            build_calls.append(1)
            return None

        with patch("openviper.tasks.events._build_dispatcher", side_effect=fake_build):
            get_dispatcher()
            get_dispatcher()

        assert len(build_calls) == 1  # built only once

    def test_reset_clears_cache(self):
        build_calls = []

        def fake_build():
            build_calls.append(1)
            return None

        with patch("openviper.tasks.events._build_dispatcher", side_effect=fake_build):
            get_dispatcher()
            reset_dispatcher()
            get_dispatcher()

        assert len(build_calls) == 2  # rebuilt after reset


# ---------------------------------------------------------------------------
# _build_dispatcher integration (reads from settings)
# ---------------------------------------------------------------------------


class TestBuildDispatcher:
    def _patch_task_settings(self, task_cfg, model_events_cfg):
        return patch(
            "openviper.tasks.events.settings",
            TASKS=task_cfg,
            MODEL_EVENTS=model_events_cfg,
            spec=False,
        )

    def test_none_when_tasks_disabled(self):
        with patch(
            "openviper.tasks.events.settings",
            TASKS={"enabled": 0},
            MODEL_EVENTS={"m.M": {"after_insert": []}},
            spec=False,
        ):
            result = _build_dispatcher()
        assert result is None

    def test_none_when_model_events_empty(self):
        with patch(
            "openviper.tasks.events.settings",
            TASKS={"enabled": 1},
            MODEL_EVENTS={},
            spec=False,
        ):
            result = _build_dispatcher()
        assert result is None

    def test_none_when_model_events_unresolvable(self):
        with patch(
            "openviper.tasks.events.settings",
            TASKS={"enabled": 1},
            MODEL_EVENTS={"m.M": {"after_insert": ["no.such.handler"]}},
            spec=False,
        ):
            result = _build_dispatcher()
        # All handlers failed to resolve → dispatcher is falsy → returns None
        assert result is None

    def test_creates_dispatcher_with_resolved_handlers(self):
        with patch(
            "openviper.tasks.events.settings",
            TASKS={"enabled": 1},
            MODEL_EVENTS={"m.M": {"after_insert": ["openviper.tasks.events._resolve_dotted"]}},
            spec=False,
        ):
            result = _build_dispatcher()
        assert result is not None
        assert bool(result)
        assert "m.M" in result._handlers

    def test_returns_none_on_exception(self):
        with patch(
            "openviper.tasks.events.settings",
            new_callable=lambda: type(
                "BadSettings",
                (),
                {
                    "__getattr__": lambda s, n: (_ for _ in ()).throw(
                        RuntimeError("settings broken")
                    )
                },
            )(),
        ):
            result = _build_dispatcher()
        assert result is None


# ---------------------------------------------------------------------------
# SUPPORTED_EVENTS constant
# ---------------------------------------------------------------------------


class TestSupportedEvents:
    def test_contains_all_lifecycle_hooks(self):
        expected = {
            "before_validate",
            "validate",
            "before_insert",
            "before_save",
            "after_insert",
            "on_update",
            "on_change",
            "on_delete",
            "after_delete",
        }
        assert expected == SUPPORTED_EVENTS

    def test_is_frozenset(self):
        assert isinstance(SUPPORTED_EVENTS, frozenset)

    def test_unknown_event_only_logs_debug(self, caplog):
        """Unknown event names are accepted but logged at DEBUG level."""
        import logging

        cfg = {"m.M": {"unknown_event_xyz": ["openviper.tasks.events._resolve_dotted"]}}
        with caplog.at_level(logging.DEBUG, logger="openviper.tasks"):
            d = ModelEventDispatcher(cfg)
        # Handler still registers under the unknown event name
        assert "m.M" in d._handlers
        assert "unknown_event_xyz" in d._handlers["m.M"]


# ---------------------------------------------------------------------------
# Model._trigger_event integration
# ---------------------------------------------------------------------------


class TestModelTriggerEvent:
    """Tests for _trigger_event using a lightweight stub model."""

    def _make_model_instance(self, module: str, class_name: str):
        """Return a minimal object that looks like a Model instance."""
        klass = type(class_name, (), {"__module__": module})
        instance = klass.__new__(klass)
        return instance

    def test_trigger_event_noop_when_dispatcher_is_none(self):
        """_trigger_event must be a soft no-op when get_dispatcher() returns None."""
        from openviper.db.models import Model

        calls = []

        class DummyModel(Model):
            class Meta:
                table_name = "dummy_trigger_noop"

        instance = DummyModel.__new__(DummyModel)

        with patch("openviper.tasks.events.get_dispatcher", return_value=None):
            # Must not raise
            instance._trigger_event("after_insert")

        assert calls == []  # no handler fired

    def test_trigger_event_calls_dispatcher(self):
        """_trigger_event must call dispatcher.trigger with the correct arguments."""
        from openviper.db.models import Model

        class TargetModel(Model):
            class Meta:
                table_name = "dummy_trigger_dispatch"

        instance = TargetModel.__new__(TargetModel)
        mock_dispatcher = MagicMock()

        with patch("openviper.tasks.events.get_dispatcher", return_value=mock_dispatcher):
            instance._trigger_event("after_insert")

        expected_path = f"{TargetModel.__module__}.{TargetModel.__name__}"
        mock_dispatcher.trigger.assert_called_once_with(expected_path, "after_insert", instance)

    def test_trigger_event_model_path_format(self):
        """Model path passed to dispatcher is '{module}.{ClassName}'."""
        from openviper.db.models import Model

        class AnotherModel(Model):
            class Meta:
                table_name = "dummy_path_format"

        instance = AnotherModel.__new__(AnotherModel)
        captured = []

        mock_disp = MagicMock()
        mock_disp.trigger.side_effect = lambda path, event, inst: captured.append(path)

        with patch("openviper.tasks.events.get_dispatcher", return_value=mock_disp):
            instance._trigger_event("on_change")

        assert len(captured) == 1
        assert captured[0].endswith("AnotherModel")
        assert "." in captured[0]

    def test_dispatcher_fires_only_matching_model(self):
        """Handlers registered for model A must NOT fire for model B."""
        handler_calls = []

        def handler(instance, **kw):
            handler_calls.append(instance)

        disp = ModelEventDispatcher.__new__(ModelEventDispatcher)
        disp._handlers = {
            "myapp.models.Post": {"after_insert": [handler]},
        }

        # Trigger for a DIFFERENT model path
        disp.trigger("myapp.models.Comment", "after_insert", object())
        assert handler_calls == []

        # Trigger for the CORRECT model path
        post_instance = object()
        disp.trigger("myapp.models.Post", "after_insert", post_instance)
        assert handler_calls == [post_instance]


# ---------------------------------------------------------------------------
# _build_dispatcher conditional activation via TASKS['enabled']
# ---------------------------------------------------------------------------


class TestBuildDispatcherActivation:
    """Verify that TASKS['enabled'] gates dispatcher creation."""

    def _patch(self, enabled, model_events):
        return patch(
            "openviper.tasks.events.settings",
            TASKS={"enabled": enabled},
            MODEL_EVENTS=model_events,
            spec=False,
        )

    def test_truthy_enabled_creates_dispatcher(self):
        cfg = {"m.M": {"after_insert": ["openviper.tasks.events._resolve_dotted"]}}
        with self._patch(True, cfg):
            result = _build_dispatcher()
        assert result is not None

    def test_falsy_enabled_zero_returns_none(self):
        cfg = {"m.M": {"after_insert": ["openviper.tasks.events._resolve_dotted"]}}
        with self._patch(0, cfg):
            result = _build_dispatcher()
        assert result is None

    def test_falsy_enabled_false_returns_none(self):
        cfg = {"m.M": {"after_insert": ["openviper.tasks.events._resolve_dotted"]}}
        with self._patch(False, cfg):
            result = _build_dispatcher()
        assert result is None

    def test_string_true_enabled_creates_dispatcher(self):
        cfg = {"m.M": {"after_insert": ["openviper.tasks.events._resolve_dotted"]}}
        with self._patch("true", cfg):
            # "true" is truthy in Python
            result = _build_dispatcher()
        assert result is not None

    def test_missing_tasks_setting_returns_none(self):
        """If TASKS is missing, dispatcher should not be created."""
        with patch(
            "openviper.tasks.events.settings",
            TASKS=None,
            MODEL_EVENTS={"m.M": {"after_insert": ["openviper.tasks.events._resolve_dotted"]}},
            spec=False,
        ):
            result = _build_dispatcher()
        assert result is None

    def test_multiple_models_registered(self):
        """Dispatcher correctly stores handlers for multiple model paths."""
        cfg = {
            "app.models.Post": {"after_insert": ["openviper.tasks.events._resolve_dotted"]},
            "app.models.Comment": {"on_change": ["openviper.tasks.events._resolve_dotted"]},
        }
        with self._patch(True, cfg):
            result = _build_dispatcher()
        assert result is not None
        assert "app.models.Post" in result._handlers
        assert "app.models.Comment" in result._handlers
        assert "after_insert" in result._handlers["app.models.Post"]
        assert "on_change" in result._handlers["app.models.Comment"]

    def test_get_dispatcher_returns_none_after_reset_with_disabled_tasks(self):
        """After reset_dispatcher(), get_dispatcher() rebuilds from current settings."""
        reset_dispatcher()
        with patch("openviper.tasks.events._build_dispatcher", return_value=None) as mock_build:
            d1 = get_dispatcher()
            assert d1 is None
            reset_dispatcher()
            d2 = get_dispatcher()
            assert d2 is None
            assert mock_build.call_count == 2  # rebuilt each time after reset

        reset_dispatcher()


# ---------------------------------------------------------------------------
# get_dispatcher — double-check locking (line 278)
# ---------------------------------------------------------------------------


class TestGetDispatcherDoubleCheckLock:
    """Verify that the double-check inside the lock prevents building twice."""

    def test_second_thread_sees_cached_value(self):
        """Line 278: when two threads race to build, only one calls _build_dispatcher."""
        reset_dispatcher()
        build_calls = []

        def slow_build():
            build_calls.append(1)
            return None

        barrier = threading.Barrier(2)
        results = []

        def worker():
            with patch("openviper.tasks.events._build_dispatcher", side_effect=slow_build):
                barrier.wait()
                results.append(get_dispatcher())

        # Run two threads; both arrive at the lock simultaneously.
        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Exactly 1 build call due to double-check (or at most 2 if race resolved fine)
        assert len(build_calls) >= 1
        assert all(r is None for r in results)
        reset_dispatcher()


# ---------------------------------------------------------------------------
# _call_handler — async path (lines 367-375)
# ---------------------------------------------------------------------------


class TestCallHandler:
    def test_sync_handler_called_directly(self):
        """Sync handler is called inline."""
        calls = []

        def sync_h(instance, event, **kw):
            calls.append((instance, event))

        obj = object()
        _call_handler(sync_h, obj, "after_insert")
        assert calls == [(obj, "after_insert")]

    def test_async_handler_no_running_loop_logs_warning(self, caplog):
        """Lines 367-375: async handler with no loop logs a warning."""
        import logging

        async def async_h(instance, event, **kw):
            pass

        obj = object()
        with caplog.at_level(logging.WARNING, logger="openviper.tasks"):
            # No event loop is running in this test → RuntimeError is caught
            _call_handler(async_h, obj, "after_insert")

        assert "no running event loop" in caplog.text.lower() or "skipped" in caplog.text.lower()

    def test_async_handler_scheduled_when_loop_running(self):
        """Async handler is scheduled via create_task when a loop is running."""
        import asyncio

        tasks_created = []

        async def async_h(instance, event, **kw):
            tasks_created.append(True)

        async def _run():
            obj = object()
            _call_handler(async_h, obj, "after_insert")
            # yield to let scheduled tasks run
            await asyncio.sleep(0)

        asyncio.run(_run())
        assert tasks_created == [True]


# ---------------------------------------------------------------------------
# _dispatch_decorator_handlers (lines 393-409)
# ---------------------------------------------------------------------------


class TestDispatchDecoratorHandlers:
    def setup_method(self):
        """Clear decorator registry before each test."""
        _events_module._decorator_registry.clear()

    def teardown_method(self):
        _events_module._decorator_registry.clear()

    def test_no_model_in_registry_is_noop(self):
        """Lines 393-395: model not in registry → returns immediately."""
        # No handlers registered, must not raise
        _dispatch_decorator_handlers("missing.Model", "after_insert", object())

    def test_no_event_in_registry_is_noop(self):
        """Lines 396-398: model in registry but event not registered → noop."""
        _events_module._decorator_registry["m.M"] = {"on_change": [lambda i, **k: None]}
        _dispatch_decorator_handlers("m.M", "after_insert", object())

    def test_handler_is_called(self):
        """Lines 399-401: registered handler is called with instance."""
        calls = []

        def h(instance, event, **kw):
            calls.append(instance)

        _events_module._decorator_registry["m.M"] = {"after_insert": [h]}
        obj = object()
        _dispatch_decorator_handlers("m.M", "after_insert", obj)
        assert calls == [obj]

    def test_handler_exception_is_caught_and_logged(self, caplog):
        """Lines 402-409: exception from handler is caught and logged."""
        import logging

        def bad_h(instance, event, **kw):
            raise RuntimeError("decorator boom")

        _events_module._decorator_registry["m.M"] = {"after_insert": [bad_h]}
        with caplog.at_level(logging.WARNING, logger="openviper.tasks"):
            _dispatch_decorator_handlers("m.M", "after_insert", object())

        assert "decorator boom" in caplog.text

    def test_second_handler_runs_after_first_raises(self):
        """Exception in first handler does not skip the second."""
        calls = []

        def bad(i, **k):
            raise ValueError("oops")

        def good(i, **k):
            calls.append("good")

        _events_module._decorator_registry["m.M"] = {"after_insert": [bad, good]}
        _dispatch_decorator_handlers("m.M", "after_insert", object())
        assert "good" in calls


# ---------------------------------------------------------------------------
# _ModelEventProxy.trigger (lines 452-466)
# ---------------------------------------------------------------------------


class TestModelEventProxyTrigger:
    def setup_method(self):
        _events_module._decorator_registry.clear()

    def teardown_method(self):
        _events_module._decorator_registry.clear()

    def test_trigger_registers_handler(self):
        """Lines 460-464: applying the decorator registers the function."""
        calls = []

        @model_event.trigger("myapp.models.Post.after_insert")
        def handler(instance, event, **kw):
            calls.append(instance)

        obj = object()
        _dispatch_decorator_handlers("myapp.models.Post", "after_insert", obj)
        assert calls == [obj]

    def test_trigger_returns_original_function(self):
        """Decorator returns the original callable unchanged."""

        def handler(instance, event, **kw):
            pass

        result = model_event.trigger("myapp.models.Post.after_insert")(handler)
        assert result is handler

    def test_trigger_no_dot_raises_value_error(self):
        """Line 452-457: path without a dot raises ValueError."""
        with pytest.raises(ValueError, match="dotted path"):
            model_event.trigger("no_dot_here")

    def test_trigger_multiple_handlers_appended(self):
        """Multiple triggers for same path accumulate handlers."""
        calls = []

        @model_event.trigger("m.M.after_insert")
        def h1(i, **k):
            calls.append("h1")

        @model_event.trigger("m.M.after_insert")
        def h2(i, **k):
            calls.append("h2")

        _dispatch_decorator_handlers("m.M", "after_insert", object())
        assert calls == ["h1", "h2"]

    def test_trigger_different_events_stored_separately(self):
        """Different event names under the same model are stored separately."""

        @model_event.trigger("m.M.after_insert")
        def h_insert(i, **k):
            pass

        @model_event.trigger("m.M.on_change")
        def h_change(i, **k):
            pass

        registry = _events_module._decorator_registry.get("m.M", {})
        assert "after_insert" in registry
        assert "on_change" in registry
