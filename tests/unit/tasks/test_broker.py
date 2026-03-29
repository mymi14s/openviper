"""Tests for openviper/tasks/broker.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import openviper.tasks.broker as broker_module
from openviper.tasks.broker import (
    _create_broker,
    _make_rabbitmq_broker,
    _make_redis_broker,
    _read_task_settings,
    get_broker,
    reset_broker,
)


@pytest.fixture(autouse=True)
def clean_broker():
    reset_broker()
    yield
    reset_broker()


def _stub_broker():
    """Return a mock that looks like a real broker."""
    b = MagicMock()
    b.add_middleware = MagicMock()
    b.close = MagicMock()
    return b


# ---------------------------------------------------------------------------
# _read_task_settings
# ---------------------------------------------------------------------------


class TestReadTaskSettings:
    def test_returns_tasks_from_settings(self) -> None:
        mock_settings = MagicMock()
        mock_settings.TASKS = {"broker": "stub", "tracking_enabled": 1}
        with patch("openviper.tasks.broker.settings", mock_settings):
            result = _read_task_settings()
        assert result["broker"] == "stub"

    def test_returns_empty_on_exception(self) -> None:
        mock_settings = MagicMock()
        type(mock_settings).TASKS = property(lambda self: (_ for _ in ()).throw(RuntimeError()))
        with patch("openviper.tasks.broker.settings", mock_settings):
            result = _read_task_settings()
        assert result == {}

    def test_returns_empty_when_tasks_none(self) -> None:
        mock_settings = MagicMock()
        mock_settings.TASKS = None
        with patch("openviper.tasks.broker.settings", mock_settings):
            result = _read_task_settings()
        assert result == {}


# ---------------------------------------------------------------------------
# get_broker / reset_broker
# ---------------------------------------------------------------------------


class TestGetBroker:
    def test_creates_broker_on_first_call(self) -> None:
        mock_broker = _stub_broker()
        with patch("openviper.tasks.broker._create_broker", return_value=mock_broker):
            b = get_broker()
        assert b is mock_broker

    def test_returns_cached_on_second_call(self) -> None:
        mock_broker = _stub_broker()
        with patch(
            "openviper.tasks.broker._create_broker", return_value=mock_broker
        ) as mock_create:
            b1 = get_broker()
            b2 = get_broker()
        assert b1 is b2
        mock_create.assert_called_once()

    def test_reset_clears_cached(self) -> None:
        mock_broker = _stub_broker()
        with patch("openviper.tasks.broker._create_broker", return_value=mock_broker):
            get_broker()
        reset_broker()
        assert broker_module._broker is None

    def test_reset_calls_close(self) -> None:
        mock_broker = _stub_broker()
        with patch("openviper.tasks.broker._create_broker", return_value=mock_broker):
            get_broker()
        reset_broker()
        mock_broker.close.assert_called_once()

    def test_reset_handles_close_exception(self) -> None:
        mock_broker = _stub_broker()
        mock_broker.close.side_effect = RuntimeError("oops")
        with patch("openviper.tasks.broker._create_broker", return_value=mock_broker):
            get_broker()
        reset_broker()  # should not raise
        assert broker_module._broker is None


# ---------------------------------------------------------------------------
# _make_redis_broker
# ---------------------------------------------------------------------------


class TestMakeRedisBroker:
    def test_creates_redis_broker(self) -> None:
        mock_redis_cls = MagicMock(return_value=_stub_broker())
        with patch.object(broker_module, "RedisBroker", mock_redis_cls):
            _make_redis_broker({"broker_url": "redis://localhost:6379/0"})
        mock_redis_cls.assert_called_once()

    def test_uses_default_url(self) -> None:
        mock_redis_cls = MagicMock(return_value=_stub_broker())
        with patch.object(broker_module, "RedisBroker", mock_redis_cls):
            _make_redis_broker({})
        call_kwargs = mock_redis_cls.call_args[1]
        assert "localhost" in call_kwargs["url"]

    def test_raises_when_unavailable(self) -> None:
        with patch.object(broker_module, "RedisBroker", None):
            with pytest.raises(ImportError):
                _make_redis_broker({})

    def test_custom_max_connections(self) -> None:
        mock_redis_cls = MagicMock(return_value=_stub_broker())
        with patch.object(broker_module, "RedisBroker", mock_redis_cls):
            _make_redis_broker({"redis_max_connections": 10})
        call_kwargs = mock_redis_cls.call_args[1]
        assert call_kwargs["max_connections"] == 10

    def test_default_max_connections(self) -> None:
        mock_redis_cls = MagicMock(return_value=_stub_broker())
        with patch.object(broker_module, "RedisBroker", mock_redis_cls):
            _make_redis_broker({})
        call_kwargs = mock_redis_cls.call_args[1]
        assert call_kwargs["max_connections"] == 50

    def test_socket_timeout(self) -> None:
        mock_redis_cls = MagicMock(return_value=_stub_broker())
        with patch.object(broker_module, "RedisBroker", mock_redis_cls):
            _make_redis_broker({"redis_socket_timeout": 5})
        call_kwargs = mock_redis_cls.call_args[1]
        assert call_kwargs["socket_timeout"] == 5

    def test_socket_connect_timeout(self) -> None:
        mock_redis_cls = MagicMock(return_value=_stub_broker())
        with patch.object(broker_module, "RedisBroker", mock_redis_cls):
            _make_redis_broker({"redis_socket_connect_timeout": 3})
        call_kwargs = mock_redis_cls.call_args[1]
        assert call_kwargs["socket_connect_timeout"] == 3

    def test_socket_keepalive(self) -> None:
        mock_redis_cls = MagicMock(return_value=_stub_broker())
        with patch.object(broker_module, "RedisBroker", mock_redis_cls):
            _make_redis_broker({"redis_socket_keepalive": True})
        call_kwargs = mock_redis_cls.call_args[1]
        assert call_kwargs["socket_keepalive"] is True


# ---------------------------------------------------------------------------
# _make_rabbitmq_broker
# ---------------------------------------------------------------------------


class TestMakeRabbitmqBroker:
    def test_creates_rabbitmq_broker(self) -> None:
        mock_rmq_cls = MagicMock(return_value=_stub_broker())
        with patch.object(broker_module, "RabbitmqBroker", mock_rmq_cls):
            _make_rabbitmq_broker({"broker_url": "amqp://localhost/"})
        mock_rmq_cls.assert_called_once()

    def test_uses_default_url(self) -> None:
        mock_rmq_cls = MagicMock(return_value=_stub_broker())
        with patch.object(broker_module, "RabbitmqBroker", mock_rmq_cls):
            _make_rabbitmq_broker({})
        call_kwargs = mock_rmq_cls.call_args[1]
        assert "amqp" in call_kwargs["url"]

    def test_raises_when_unavailable(self) -> None:
        with patch.object(broker_module, "RabbitmqBroker", None):
            with pytest.raises(ImportError):
                _make_rabbitmq_broker({})


# ---------------------------------------------------------------------------
# _create_broker — backend selection
# ---------------------------------------------------------------------------


class TestCreateBroker:
    def _patch_all(self, cfg: dict, broker_obj=None) -> tuple:
        if broker_obj is None:
            broker_obj = _stub_broker()
        return broker_obj

    def test_stub_backend(self) -> None:
        mock_stub = MagicMock(return_value=_stub_broker())
        with (
            patch("openviper.tasks.broker._read_task_settings", return_value={"broker": "stub"}),
            patch.object(broker_module, "StubBroker", mock_stub),
            patch("openviper.tasks.broker.dramatiq"),
        ):
            b = _create_broker()
        assert b is not None

    def test_stub_backend_unavailable(self) -> None:
        with (
            patch("openviper.tasks.broker._read_task_settings", return_value={"broker": "stub"}),
            patch.object(broker_module, "StubBroker", None),
        ):
            with pytest.raises(ImportError):
                _create_broker()

    def test_redis_backend(self) -> None:
        mock_broker_obj = _stub_broker()
        with (
            patch("openviper.tasks.broker._read_task_settings", return_value={"broker": "redis"}),
            patch("openviper.tasks.broker._make_redis_broker", return_value=mock_broker_obj),
            patch("openviper.tasks.broker.dramatiq"),
        ):
            b = _create_broker()
        assert b is mock_broker_obj

    def test_rabbitmq_backend(self) -> None:
        mock_broker_obj = _stub_broker()
        with (
            patch(
                "openviper.tasks.broker._read_task_settings", return_value={"broker": "rabbitmq"}
            ),
            patch("openviper.tasks.broker._make_rabbitmq_broker", return_value=mock_broker_obj),
            patch("openviper.tasks.broker.dramatiq"),
        ):
            b = _create_broker()
        assert b is mock_broker_obj

    def test_invalid_backend_raises(self) -> None:
        with (
            patch(
                "openviper.tasks.broker._read_task_settings",
                return_value={"broker": "badbroker"},
            ),
        ):
            with pytest.raises(ValueError, match="Unknown TASKS broker"):
                _create_broker()

    def test_tracking_enabled(self) -> None:
        mock_broker_obj = _stub_broker()
        with (
            patch(
                "openviper.tasks.broker._read_task_settings",
                return_value={"broker": "stub", "tracking_enabled": 1},
            ),
            patch.object(broker_module, "StubBroker", MagicMock(return_value=mock_broker_obj)),
            patch("openviper.tasks.broker.dramatiq"),
        ):
            _create_broker()
        mock_broker_obj.add_middleware.assert_called()

    def test_tracking_enabled_exception_handled(self) -> None:
        mock_broker_obj = _stub_broker()
        mock_broker_obj.add_middleware.side_effect = [None, RuntimeError("oops")]
        with (
            patch(
                "openviper.tasks.broker._read_task_settings",
                return_value={"broker": "stub", "tracking_enabled": 1},
            ),
            patch.object(broker_module, "StubBroker", MagicMock(return_value=mock_broker_obj)),
            patch("openviper.tasks.broker.dramatiq"),
        ):
            _create_broker()  # should not raise

    def test_scheduler_enabled(self) -> None:
        mock_broker_obj = _stub_broker()
        with (
            patch(
                "openviper.tasks.broker._read_task_settings",
                return_value={"broker": "stub", "scheduler_enabled": 1},
            ),
            patch.object(broker_module, "StubBroker", MagicMock(return_value=mock_broker_obj)),
            patch("openviper.tasks.broker.dramatiq"),
        ):
            _create_broker()
        mock_broker_obj.add_middleware.assert_called()

    def test_scheduler_enabled_exception_handled(self) -> None:
        mock_broker_obj = _stub_broker()
        mock_broker_obj.add_middleware.side_effect = [None, RuntimeError("sched error")]
        with (
            patch(
                "openviper.tasks.broker._read_task_settings",
                return_value={"broker": "stub", "scheduler_enabled": 1},
            ),
            patch.object(broker_module, "StubBroker", MagicMock(return_value=mock_broker_obj)),
            patch("openviper.tasks.broker.dramatiq"),
        ):
            _create_broker()  # should not raise

    def test_cleanup_enabled(self) -> None:
        mock_broker_obj = _stub_broker()
        mock_cleanup = MagicMock()
        with (
            patch(
                "openviper.tasks.broker._read_task_settings",
                return_value={"broker": "stub", "cleanup_enabled": 1},
            ),
            patch.object(broker_module, "StubBroker", MagicMock(return_value=mock_broker_obj)),
            patch("openviper.tasks.broker.setup_cleanup_task", mock_cleanup),
            patch("openviper.tasks.broker.dramatiq"),
        ):
            _create_broker()
        mock_cleanup.assert_called_once()

    def test_cleanup_enabled_exception_handled(self) -> None:
        mock_broker_obj = _stub_broker()
        with (
            patch(
                "openviper.tasks.broker._read_task_settings",
                return_value={"broker": "stub", "cleanup_enabled": 1},
            ),
            patch.object(broker_module, "StubBroker", MagicMock(return_value=mock_broker_obj)),
            patch("openviper.tasks.broker.setup_cleanup_task", side_effect=RuntimeError("oops")),
            patch("openviper.tasks.broker.dramatiq"),
        ):
            _create_broker()  # should not raise

    def test_backend_url_attaches_result_backend(self) -> None:
        mock_broker_obj = _stub_broker()
        mock_results_cls = MagicMock(return_value=MagicMock())
        mock_redis_backend_cls = MagicMock(return_value=MagicMock())
        with (
            patch(
                "openviper.tasks.broker._read_task_settings",
                return_value={"broker": "stub", "backend_url": "redis://localhost:6379/1"},
            ),
            patch.object(broker_module, "StubBroker", MagicMock(return_value=mock_broker_obj)),
            patch.object(broker_module, "Results", mock_results_cls),
            patch.object(broker_module, "RedisBackend", mock_redis_backend_cls),
            patch("openviper.tasks.broker.dramatiq"),
        ):
            _create_broker()
        mock_broker_obj.add_middleware.assert_called()

    def test_backend_url_unavailable_results(self) -> None:
        mock_broker_obj = _stub_broker()
        with (
            patch(
                "openviper.tasks.broker._read_task_settings",
                return_value={"broker": "stub", "backend_url": "redis://localhost/1"},
            ),
            patch.object(broker_module, "StubBroker", MagicMock(return_value=mock_broker_obj)),
            patch.object(broker_module, "Results", None),
            patch.object(broker_module, "RedisBackend", None),
            patch("openviper.tasks.broker.dramatiq"),
        ):
            _create_broker()  # should not raise

    def test_backend_url_exception_handled(self) -> None:
        mock_broker_obj = _stub_broker()
        mock_redis_backend_cls = MagicMock(side_effect=RuntimeError("conn failed"))
        with (
            patch(
                "openviper.tasks.broker._read_task_settings",
                return_value={"broker": "stub", "backend_url": "redis://localhost/1"},
            ),
            patch.object(broker_module, "StubBroker", MagicMock(return_value=mock_broker_obj)),
            patch.object(broker_module, "Results", MagicMock()),
            patch.object(broker_module, "RedisBackend", mock_redis_backend_cls),
            patch("openviper.tasks.broker.dramatiq"),
        ):
            _create_broker()  # should not raise


# ---------------------------------------------------------------------------
# _create_broker — None middleware branches
# ---------------------------------------------------------------------------


class TestCreateBrokerNoneMiddleware:
    def test_tracking_middleware_is_none_warns(self) -> None:
        mock_broker_obj = _stub_broker()
        with (
            patch(
                "openviper.tasks.broker._read_task_settings",
                return_value={"broker": "stub", "tracking_enabled": 1},
            ),
            patch.object(broker_module, "StubBroker", MagicMock(return_value=mock_broker_obj)),
            patch.object(broker_module, "TaskTrackingMiddleware", None),
            patch("openviper.tasks.broker.dramatiq"),
        ):
            _create_broker()  # should not raise; logs warning

    def test_scheduler_middleware_is_none_warns(self) -> None:
        mock_broker_obj = _stub_broker()
        with (
            patch(
                "openviper.tasks.broker._read_task_settings",
                return_value={"broker": "stub", "scheduler_enabled": 1},
            ),
            patch.object(broker_module, "StubBroker", MagicMock(return_value=mock_broker_obj)),
            patch.object(broker_module, "SchedulerMiddleware", None),
            patch("openviper.tasks.broker.dramatiq"),
        ):
            _create_broker()  # should not raise

    def test_cleanup_task_is_none_warns(self) -> None:
        mock_broker_obj = _stub_broker()
        with (
            patch(
                "openviper.tasks.broker._read_task_settings",
                return_value={"broker": "stub", "cleanup_enabled": 1},
            ),
            patch.object(broker_module, "StubBroker", MagicMock(return_value=mock_broker_obj)),
            patch.object(broker_module, "setup_cleanup_task", None),
            patch("openviper.tasks.broker.dramatiq"),
        ):
            _create_broker()  # should not raise
