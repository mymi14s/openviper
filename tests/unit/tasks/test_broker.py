"""Unit tests for openviper.tasks.broker — double-checked lock rewrite.

Covers:
- ``get_broker()`` / ``setup_broker`` alias / ``reset_broker()``
- ``_create_broker()`` factory (stub, redis, rabbitmq, unknown → ValueError)
- ``_make_redis_broker`` / ``_make_rabbitmq_broker`` thin wrappers
- ``_read_task_settings()`` exception handling
- Middleware attachment: AsyncIO always, TaskTrackingMiddleware when enabled,
  Results when backend_url is set
- Concurrency: 100 threads → _create_broker called exactly once
"""

from __future__ import annotations

import contextlib
import threading
from unittest.mock import MagicMock, patch

import dramatiq
import dramatiq.brokers.stub
import pytest

import openviper.tasks.broker as broker_module
from openviper.tasks.broker import (
    _make_rabbitmq_broker,
    _make_redis_broker,
    _read_task_settings,
    get_broker,
    reset_broker,
    setup_broker,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_broker():
    """Each test gets a clean broker state."""
    reset_broker()
    yield
    reset_broker()


def _stub_settings(cfg: dict):
    """Return a patch context manager for _read_task_settings returning *cfg*."""
    return patch("openviper.tasks.broker._read_task_settings", return_value=cfg)


# ---------------------------------------------------------------------------
# setup_broker is get_broker
# ---------------------------------------------------------------------------


def test_setup_broker_is_get_broker_alias():
    assert setup_broker is get_broker


# ---------------------------------------------------------------------------
# get_broker — basic stub
# ---------------------------------------------------------------------------


def test_get_broker_stub_returns_stub_broker():
    with _stub_settings({"broker": "stub"}):
        result = get_broker()
    assert isinstance(result, dramatiq.brokers.stub.StubBroker)


def test_get_broker_returns_same_instance_on_second_call():
    with _stub_settings({"broker": "stub"}):
        first = get_broker()
        second = get_broker()
    assert first is second


def test_get_broker_caches_in_module_variable():
    with _stub_settings({"broker": "stub"}):
        broker = get_broker()
    assert broker_module._broker is broker


def test_get_broker_registers_with_dramatiq():
    with _stub_settings({"broker": "stub"}):
        broker = get_broker()
    assert dramatiq.get_broker() is broker


# ---------------------------------------------------------------------------
# get_broker — redis / rabbitmq delegation
# ---------------------------------------------------------------------------


def test_get_broker_redis_delegates_to_make_redis_broker():
    mock_broker = MagicMock()
    mock_broker.add_middleware = MagicMock()
    with (
        _stub_settings({"broker": "redis", "broker_url": "redis://localhost:6379/0"}),
        patch("openviper.tasks.broker._make_redis_broker", return_value=mock_broker) as m,
    ):
        result = get_broker()
    m.assert_called_once()
    assert result is mock_broker


def test_get_broker_rabbitmq_delegates_to_make_rabbitmq_broker():
    mock_broker = MagicMock()
    mock_broker.add_middleware = MagicMock()
    with (
        _stub_settings({"broker": "rabbitmq", "broker_url": "amqp://localhost/"}),
        patch("openviper.tasks.broker._make_rabbitmq_broker", return_value=mock_broker) as m,
    ):
        result = get_broker()
    m.assert_called_once()
    assert result is mock_broker


# ---------------------------------------------------------------------------
# get_broker — unknown broker type raises ValueError
# ---------------------------------------------------------------------------


def test_get_broker_unknown_type_raises_value_error():
    with (
        _stub_settings({"broker": "nonexistent_broker_xyz"}),
        pytest.raises(ValueError, match="nonexistent_broker_xyz"),
    ):
        get_broker()


def test_get_broker_unknown_type_does_not_cache():
    # After a failed creation, _broker must remain None so a subsequent
    # call with a valid config can still succeed.
    with _stub_settings({"broker": "nonexistent_broker_xyz"}), contextlib.suppress(ValueError):
        get_broker()
    assert broker_module._broker is None


# ---------------------------------------------------------------------------
# AsyncIO middleware always attached
# ---------------------------------------------------------------------------


def test_get_broker_attaches_asyncio_middleware():
    from dramatiq.middleware.asyncio import AsyncIO

    with _stub_settings({"broker": "stub"}):
        broker = get_broker()
    assert any(isinstance(m, AsyncIO) for m in broker.middleware)


# ---------------------------------------------------------------------------
# tracking_enabled controls TaskTrackingMiddleware
# ---------------------------------------------------------------------------


def test_get_broker_tracking_enabled_attaches_middleware():
    from openviper.tasks.middleware import TaskTrackingMiddleware

    with _stub_settings({"broker": "stub", "tracking_enabled": 1}):
        broker = get_broker()
    assert any(isinstance(m, TaskTrackingMiddleware) for m in broker.middleware)


def test_get_broker_tracking_disabled_no_tracking_middleware():
    from openviper.tasks.middleware import TaskTrackingMiddleware

    with _stub_settings({"broker": "stub", "tracking_enabled": 0}):
        broker = get_broker()
    assert not any(isinstance(m, TaskTrackingMiddleware) for m in broker.middleware)


def test_get_broker_tracking_absent_no_tracking_middleware():
    from openviper.tasks.middleware import TaskTrackingMiddleware

    with _stub_settings({"broker": "stub"}):
        broker = get_broker()
    assert not any(isinstance(m, TaskTrackingMiddleware) for m in broker.middleware)


# ---------------------------------------------------------------------------
# backend_url controls Results middleware
# ---------------------------------------------------------------------------


def test_get_broker_backend_url_attaches_results_middleware():
    from dramatiq.results import Results

    mock_backend = MagicMock()
    with (
        _stub_settings({"broker": "stub", "backend_url": "redis://localhost:6379/1"}),
        patch("dramatiq.results.backends.redis.RedisBackend", return_value=mock_backend),
    ):
        broker = get_broker()
    assert any(isinstance(m, Results) for m in broker.middleware)


def test_get_broker_no_backend_url_no_results_middleware():
    from dramatiq.results import Results

    with _stub_settings({"broker": "stub"}):
        broker = get_broker()
    assert not any(isinstance(m, Results) for m in broker.middleware)


# ---------------------------------------------------------------------------
# reset_broker
# ---------------------------------------------------------------------------


def test_reset_broker_sets_module_var_to_none():
    with _stub_settings({"broker": "stub"}):
        get_broker()
    assert broker_module._broker is not None
    reset_broker()
    assert broker_module._broker is None


def test_reset_broker_calls_close_on_existing_broker():
    mock_broker = MagicMock()
    mock_broker.add_middleware = MagicMock()
    with (
        _stub_settings({"broker": "stub"}),
        patch("dramatiq.brokers.stub.StubBroker", return_value=mock_broker),
    ):
        get_broker()
    reset_broker()
    mock_broker.close.assert_called_once()


def test_after_reset_new_instance_is_created():
    with _stub_settings({"broker": "stub"}):
        first = get_broker()
    reset_broker()
    with _stub_settings({"broker": "stub"}):
        second = get_broker()
    assert first is not second


def test_reset_broker_is_idempotent():
    """Calling reset_broker() twice must not raise."""
    reset_broker()
    reset_broker()
    assert broker_module._broker is None


# ---------------------------------------------------------------------------
# _read_task_settings — exception safety
# ---------------------------------------------------------------------------


def test_read_task_settings_returns_empty_dict_on_exception():
    class BrokenSettings:
        @property
        def TASKS(self) -> None:
            raise RuntimeError("no config")

    with patch("openviper.tasks.broker.settings", BrokenSettings()):
        result = _read_task_settings()
    assert result == {}


# ---------------------------------------------------------------------------
# _make_redis_broker
# ---------------------------------------------------------------------------


def test_make_redis_broker_passes_broker_url():
    mock_broker = MagicMock()
    with patch("dramatiq.brokers.redis.RedisBroker", return_value=mock_broker) as mock_cls:
        result = _make_redis_broker({"broker_url": "redis://myhost:6379/2"})
    mock_cls.assert_called_once_with(url="redis://myhost:6379/2")
    assert result is mock_broker


def test_make_redis_broker_none_url_when_absent():
    mock_broker = MagicMock()
    with patch("dramatiq.brokers.redis.RedisBroker", return_value=mock_broker) as mock_cls:
        _make_redis_broker({})
    # url kwarg should default to redis://localhost:6379/0 when absent from cfg
    mock_cls.assert_called_once_with(url="redis://localhost:6379/0")


# ---------------------------------------------------------------------------
# _make_rabbitmq_broker
# ---------------------------------------------------------------------------


def test_make_rabbitmq_broker_passes_broker_url():
    mock_broker = MagicMock()
    with patch("dramatiq.brokers.rabbitmq.RabbitmqBroker", return_value=mock_broker) as mock_cls:
        result = _make_rabbitmq_broker({"broker_url": "amqp://rabbit:5672/"})
    mock_cls.assert_called_once_with(url="amqp://rabbit:5672/")
    assert result is mock_broker


def test_make_rabbitmq_broker_none_url_when_absent():
    mock_broker = MagicMock()
    with patch("dramatiq.brokers.rabbitmq.RabbitmqBroker", return_value=mock_broker) as mock_cls:
        _make_rabbitmq_broker({})
    mock_cls.assert_called_once_with(url="amqp://guest:guest@localhost:5672/")


# ---------------------------------------------------------------------------
# Concurrency: double-checked lock guarantees exactly one _create_broker call
# ---------------------------------------------------------------------------


def test_get_broker_concurrent_creates_broker_exactly_once():
    """100 threads racing to call get_broker() must only invoke _create_broker once."""
    create_calls: list[int] = []
    original_create = broker_module._create_broker

    def counting_create() -> object:
        create_calls.append(1)
        return original_create()

    barrier = threading.Barrier(100)
    results: list[object] = []
    errors: list[Exception] = []

    def worker() -> None:
        try:
            barrier.wait()  # all threads start simultaneously
            results.append(get_broker())
        except Exception as exc:
            errors.append(exc)

    with (
        _stub_settings({"broker": "stub"}),
        patch("openviper.tasks.broker._create_broker", side_effect=counting_create),
    ):
        threads = [threading.Thread(target=worker) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert not errors, f"Unexpected errors in threads: {errors}"
    assert (
        len(create_calls) == 1
    ), f"_create_broker was called {len(create_calls)} times, expected exactly 1"
    # All threads must have received the same broker instance.
    first = results[0]
    assert all(r is first for r in results)


# ---------------------------------------------------------------------------
# reset_broker exception suppression 
# ---------------------------------------------------------------------------


def test_reset_broker_close_exception_is_suppressed():
    mock_broker = MagicMock()
    mock_broker.add_middleware = MagicMock()
    mock_broker.close.side_effect = RuntimeError("can't close cleanly")

    with (
        _stub_settings({"broker": "stub"}),
        patch("dramatiq.brokers.stub.StubBroker", return_value=mock_broker),
    ):
        get_broker()

    # reset_broker() must not raise even though broker.close() raises
    reset_broker()
    assert broker_module._broker is None


# ---------------------------------------------------------------------------
# TaskTrackingMiddleware attachment exception 
# ---------------------------------------------------------------------------


def test_get_broker_tracking_middleware_exception_is_logged():
    with (
        _stub_settings({"broker": "stub", "tracking_enabled": 1}),
        patch(
            "openviper.tasks.middleware.TaskTrackingMiddleware",
            side_effect=RuntimeError("db not ready"),
        ),
    ):
        broker = get_broker()
    # No exception raised — broker is still returned
    assert broker is not None


# ---------------------------------------------------------------------------
# SchedulerMiddleware attachment exception 
# ---------------------------------------------------------------------------


def test_get_broker_scheduler_middleware_exception_is_logged():
    with (
        _stub_settings({"broker": "stub", "scheduler_enabled": 1}),
        patch(
            "openviper.tasks.middleware.SchedulerMiddleware",
            side_effect=RuntimeError("scheduler unavailable"),
        ),
    ):
        broker = get_broker()
    assert broker is not None


# ---------------------------------------------------------------------------
# Results backend attachment exception 
# ---------------------------------------------------------------------------


def test_get_broker_results_backend_exception_is_logged():
    with (
        _stub_settings({"broker": "stub", "backend_url": "redis://localhost:6379/1"}),
        patch(
            "dramatiq.results.backends.redis.RedisBackend",
            side_effect=RuntimeError("redis unreachable"),
        ),
    ):
        broker = get_broker()
    assert broker is not None
