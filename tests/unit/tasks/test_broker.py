"""Unit tests for openviper.tasks.broker — Broker factory."""

import logging
import threading
from unittest.mock import MagicMock, patch

import pytest

from openviper.tasks.broker import (
    _create_broker,
    _make_rabbitmq_broker,
    _make_redis_broker,
    _read_task_settings,
    get_broker,
    reset_broker,
    setup_broker,
)


class TestGetBroker:
    """Test get_broker function."""

    def test_returns_broker(self):
        """get_broker should return a broker instance."""
        reset_broker()  # Clean state
        with patch("openviper.tasks.broker._create_broker") as mock_create:
            mock_broker = MagicMock()
            mock_create.return_value = mock_broker

            broker = get_broker()

            assert broker is mock_broker
            mock_create.assert_called_once()

    def test_caches_broker(self):
        """get_broker should return cached broker on subsequent calls."""
        reset_broker()
        with patch("openviper.tasks.broker._create_broker") as mock_create:
            mock_broker = MagicMock()
            mock_create.return_value = mock_broker

            broker1 = get_broker()
            broker2 = get_broker()

            assert broker1 is broker2
            # Should only create once
            mock_create.assert_called_once()

    def test_thread_safe(self):
        """get_broker should be thread-safe."""

        reset_broker()
        results = []

        with patch("openviper.tasks.broker._create_broker") as mock_create:
            mock_broker = MagicMock()
            mock_create.return_value = mock_broker

            def get_and_store():
                results.append(get_broker())

            threads = [threading.Thread(target=get_and_store) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # All threads should get the same broker
            assert all(b is results[0] for b in results)
            # Broker should only be created once
            mock_create.assert_called_once()


class TestSetupBroker:
    """Test setup_broker alias."""

    def test_setup_broker_is_alias(self):
        """setup_broker should be an alias for get_broker."""
        assert setup_broker is get_broker


class TestResetBroker:
    """Test reset_broker function."""

    def test_resets_broker(self):
        """reset_broker should clear the cached broker."""
        reset_broker()
        with patch("openviper.tasks.broker._create_broker") as mock_create:
            mock_broker1 = MagicMock()
            mock_broker2 = MagicMock()
            mock_create.side_effect = [mock_broker1, mock_broker2]

            broker1 = get_broker()
            reset_broker()
            broker2 = get_broker()

            assert broker1 is not broker2
            assert mock_create.call_count == 2

    def test_closes_broker(self):
        """reset_broker should call close() on the broker."""
        reset_broker()
        with patch("openviper.tasks.broker._create_broker") as mock_create:
            mock_broker = MagicMock()
            mock_create.return_value = mock_broker

            get_broker()
            reset_broker()

            mock_broker.close.assert_called_once()

    def test_handles_close_error(self):
        """reset_broker should suppress errors from close()."""
        reset_broker()
        with patch("openviper.tasks.broker._create_broker") as mock_create:
            mock_broker = MagicMock()
            mock_broker.close.side_effect = Exception("Close failed")
            mock_create.return_value = mock_broker

            get_broker()
            # Should not raise
            reset_broker()


class TestReadTaskSettings:
    """Test _read_task_settings helper."""

    @patch("openviper.tasks.broker.settings")
    def test_reads_tasks_dict(self, mock_settings):
        """Should return TASKS dict from settings."""
        mock_settings.TASKS = {"broker": "redis", "enabled": 1}

        result = _read_task_settings()

        assert result == {"broker": "redis", "enabled": 1}

    @patch("openviper.tasks.broker.settings")
    def test_returns_empty_dict_on_error(self, mock_settings):
        """Should return empty dict if settings access fails."""
        # Simulate attribute error
        type(mock_settings).TASKS = property(lambda self: (_ for _ in ()).throw(Exception("fail")))

        result = _read_task_settings()

        assert result == {}

    @patch("openviper.tasks.broker.settings")
    def test_handles_none_tasks(self, mock_settings):
        """Should return empty dict if TASKS is None."""
        mock_settings.TASKS = None

        result = _read_task_settings()

        assert result == {}


class TestCreateBroker:
    """Test _create_broker function."""

    @patch("openviper.tasks.broker._read_task_settings")
    @patch("openviper.tasks.broker._make_redis_broker")
    @patch("openviper.tasks.broker.dramatiq.set_broker")
    def test_creates_redis_broker_by_default(
        self, mock_set_broker, mock_make_redis, mock_read_settings
    ):
        """Should create Redis broker when broker='redis'."""
        mock_read_settings.return_value = {"broker": "redis"}
        mock_redis_broker = MagicMock()
        mock_make_redis.return_value = mock_redis_broker

        broker = _create_broker()

        mock_make_redis.assert_called_once()
        assert broker is mock_redis_broker
        mock_set_broker.assert_called_once_with(mock_redis_broker)

    @patch("openviper.tasks.broker._read_task_settings")
    @patch("openviper.tasks.broker._make_rabbitmq_broker")
    @patch("openviper.tasks.broker.dramatiq.set_broker")
    def test_creates_rabbitmq_broker(self, mock_set_broker, mock_make_rabbitmq, mock_read_settings):
        """Should create RabbitMQ broker when broker='rabbitmq'."""
        mock_read_settings.return_value = {"broker": "rabbitmq"}
        mock_rabbitmq_broker = MagicMock()
        mock_make_rabbitmq.return_value = mock_rabbitmq_broker

        broker = _create_broker()

        mock_make_rabbitmq.assert_called_once()
        assert broker is mock_rabbitmq_broker

    @patch("openviper.tasks.broker._read_task_settings")
    @patch("openviper.tasks.broker.dramatiq.set_broker")
    def test_creates_stub_broker(self, mock_set_broker, mock_read_settings):
        """Should create StubBroker when broker='stub'."""
        mock_read_settings.return_value = {"broker": "stub"}

        broker = _create_broker()

        # Check that it's a StubBroker
        assert broker.__class__.__name__ == "StubBroker"

    @patch("openviper.tasks.broker._read_task_settings")
    def test_raises_for_unknown_broker(self, mock_read_settings):
        """Should raise ValueError for unknown broker type."""
        mock_read_settings.return_value = {"broker": "unknown"}

        with pytest.raises(ValueError, match="Unknown TASKS broker"):
            _create_broker()

    @patch("openviper.tasks.broker._read_task_settings")
    @patch("openviper.tasks.broker._make_redis_broker")
    @patch("openviper.tasks.broker.dramatiq.set_broker")
    def test_adds_asyncio_middleware(self, mock_set_broker, mock_make_redis, mock_read_settings):
        """Should add AsyncIO middleware to broker."""
        mock_read_settings.return_value = {"broker": "redis"}
        mock_broker = MagicMock()
        mock_make_redis.return_value = mock_broker

        _create_broker()

        # Should have called add_middleware for AsyncIO
        mock_broker.add_middleware.assert_called()
        # Check if AsyncIO middleware was added
        calls = mock_broker.add_middleware.call_args_list
        assert any("AsyncIO" in str(call) for call in calls)

    @patch("openviper.tasks.broker._read_task_settings")
    @patch("openviper.tasks.broker._make_redis_broker")
    @patch("openviper.tasks.broker.dramatiq.set_broker")
    def test_adds_tracking_middleware_when_enabled(
        self, mock_set_broker, mock_make_redis, mock_read_settings
    ):
        """Should add TaskTrackingMiddleware when tracking_enabled=1."""
        mock_read_settings.return_value = {
            "broker": "redis",
            "tracking_enabled": 1,
        }
        mock_broker = MagicMock()
        mock_make_redis.return_value = mock_broker

        with patch("openviper.tasks.middleware.TaskTrackingMiddleware") as mock_tracking:
            _create_broker()

            mock_tracking.assert_called_once()

    @patch("openviper.tasks.broker._read_task_settings")
    @patch("openviper.tasks.broker._make_redis_broker")
    @patch("openviper.tasks.broker.dramatiq.set_broker")
    def test_skips_tracking_middleware_when_disabled(
        self, mock_set_broker, mock_make_redis, mock_read_settings
    ):
        """Should not add TaskTrackingMiddleware when tracking_enabled=0."""
        mock_read_settings.return_value = {
            "broker": "redis",
            "tracking_enabled": 0,
        }
        mock_broker = MagicMock()
        mock_make_redis.return_value = mock_broker

        with patch("openviper.tasks.middleware.TaskTrackingMiddleware") as mock_tracking:
            _create_broker()

            mock_tracking.assert_not_called()

    @patch("openviper.tasks.broker._read_task_settings")
    @patch("openviper.tasks.broker._make_redis_broker")
    @patch("openviper.tasks.broker.dramatiq.set_broker")
    def test_adds_scheduler_middleware_when_enabled(
        self, mock_set_broker, mock_make_redis, mock_read_settings
    ):
        """Should add SchedulerMiddleware when scheduler_enabled=1."""
        mock_read_settings.return_value = {
            "broker": "redis",
            "scheduler_enabled": 1,
        }
        mock_broker = MagicMock()
        mock_make_redis.return_value = mock_broker

        with patch("openviper.tasks.middleware.SchedulerMiddleware") as mock_scheduler:
            _create_broker()

            mock_scheduler.assert_called_once()


class TestMakeRedisBroker:
    """Test _make_redis_broker function."""

    @patch("dramatiq.brokers.redis.RedisBroker")
    def test_creates_redis_broker_with_default_url(self, mock_redis_broker_class):
        """Should create RedisBroker with default URL."""
        cfg = {}

        _make_redis_broker(cfg)

        call_kwargs = mock_redis_broker_class.call_args[1]
        assert "url" in call_kwargs
        assert call_kwargs["url"] == "redis://localhost:6379/0"

    @patch("dramatiq.brokers.redis.RedisBroker")
    def test_creates_redis_broker_with_custom_url(self, mock_redis_broker_class):
        """Should create RedisBroker with custom URL from config."""
        cfg = {"broker_url": "redis://custom:6380/1"}

        _make_redis_broker(cfg)

        call_kwargs = mock_redis_broker_class.call_args[1]
        assert call_kwargs["url"] == "redis://custom:6380/1"

    @patch("dramatiq.brokers.redis.RedisBroker")
    def test_sets_max_connections(self, mock_redis_broker_class):
        """Should set max_connections from config."""
        cfg = {"redis_max_connections": 100}

        _make_redis_broker(cfg)

        call_kwargs = mock_redis_broker_class.call_args[1]
        assert call_kwargs["max_connections"] == 100

    @patch("dramatiq.brokers.redis.RedisBroker")
    def test_default_max_connections(self, mock_redis_broker_class):
        """Should use default max_connections of 50."""
        cfg = {}

        _make_redis_broker(cfg)

        call_kwargs = mock_redis_broker_class.call_args[1]
        assert call_kwargs["max_connections"] == 50


class TestMakeRabbitmqBroker:
    """Test _make_rabbitmq_broker function."""

    @patch("dramatiq.brokers.rabbitmq.RabbitmqBroker")
    def test_creates_rabbitmq_broker_with_default_url(self, mock_rabbitmq_broker_class):
        """Should create RabbitmqBroker with default URL."""
        cfg = {}

        _make_rabbitmq_broker(cfg)

        call_kwargs = mock_rabbitmq_broker_class.call_args[1]
        assert call_kwargs["url"] == "amqp://guest:guest@localhost:5672/"

    @patch("dramatiq.brokers.rabbitmq.RabbitmqBroker")
    def test_creates_rabbitmq_broker_with_custom_url(self, mock_rabbitmq_broker_class):
        """Should create RabbitmqBroker with custom URL from config."""
        cfg = {"broker_url": "amqp://user:pass@example.com:5672/"}

        _make_rabbitmq_broker(cfg)

        call_kwargs = mock_rabbitmq_broker_class.call_args[1]
        assert call_kwargs["url"] == "amqp://user:pass@example.com:5672/"


class TestRedisBrokerUrlSecurity:
    """Security: Redis URL password must not appear in logs."""

    @patch("dramatiq.brokers.redis.RedisBroker")
    def test_password_not_logged(self, mock_redis_broker_class, caplog):
        """Redis password in URL must be redacted from debug log output."""

        cfg = {"broker_url": "redis://:s3cr3t@myhost:6379/0"}

        with caplog.at_level(logging.DEBUG, logger="openviper.tasks"):
            _make_redis_broker(cfg)

        for record in caplog.records:
            assert "s3cr3t" not in record.getMessage()

    @patch("dramatiq.brokers.redis.RedisBroker")
    def test_host_still_logged(self, mock_redis_broker_class, caplog):
        """Host/port portion of Redis URL should still appear in log."""

        cfg = {"broker_url": "redis://:s3cr3t@myhost:6379/0"}

        with caplog.at_level(logging.DEBUG, logger="openviper.tasks"):
            _make_redis_broker(cfg)

        logged = " ".join(r.getMessage() for r in caplog.records)
        assert "myhost" in logged


# ── _make_redis_broker: socket options (lines 213, 215, 217) ────────────────


class TestMakeRedisBrokerSocketOptions:
    @patch("dramatiq.brokers.redis.RedisBroker")
    def test_socket_timeout_set_when_configured(self, mock_redis_class):
        """redis_socket_timeout configures socket_timeout kwarg (line 213)."""
        cfg = {"broker_url": "redis://localhost:6379", "redis_socket_timeout": 10}
        _make_redis_broker(cfg)
        _, kwargs = mock_redis_class.call_args
        assert kwargs["socket_timeout"] == 10

    @patch("dramatiq.brokers.redis.RedisBroker")
    def test_socket_connect_timeout_set_when_configured(self, mock_redis_class):
        """redis_socket_connect_timeout configures socket_connect_timeout kwarg (line 215)."""
        cfg = {"broker_url": "redis://localhost:6379", "redis_socket_connect_timeout": 5}
        _make_redis_broker(cfg)
        _, kwargs = mock_redis_class.call_args
        assert kwargs["socket_connect_timeout"] == 5

    @patch("dramatiq.brokers.redis.RedisBroker")
    def test_socket_keepalive_set_when_configured(self, mock_redis_class):
        """redis_socket_keepalive configures socket_keepalive kwarg (line 217)."""
        cfg = {"broker_url": "redis://localhost:6379", "redis_socket_keepalive": True}
        _make_redis_broker(cfg)
        _, kwargs = mock_redis_class.call_args
        assert kwargs["socket_keepalive"] is True


# ── _create_broker exception paths (lines 144-145, 156-157, 162-167, 172-183) ─


class TestCreateBrokerExceptionPaths:
    @patch("openviper.tasks.broker.dramatiq.set_broker")
    @patch("openviper.tasks.broker._make_redis_broker")
    def test_tracking_middleware_exception_logged(self, mock_redis, mock_set_broker):
        """Exception importing TaskTrackingMiddleware is caught and logged (lines 144-145)."""
        mock_redis.return_value = MagicMock()

        with patch(
            "openviper.tasks.broker._read_task_settings", return_value={"tracking_enabled": True}
        ):
            with patch("openviper.tasks.broker.logger") as mock_logger:
                with patch.dict("sys.modules", {"openviper.tasks.middleware": None}):
                    _create_broker()

        assert any(
            "TaskTrackingMiddleware" in str(c) or "Could not" in str(c)
            for c in mock_logger.warning.call_args_list
        )

    @patch("openviper.tasks.broker.dramatiq.set_broker")
    @patch("openviper.tasks.broker._make_redis_broker")
    def test_scheduler_middleware_exception_logged(self, mock_redis, mock_set_broker):
        """Exception importing SchedulerMiddleware is caught and logged (lines 156-157)."""
        mock_redis.return_value = MagicMock()

        with patch(
            "openviper.tasks.broker._read_task_settings", return_value={"scheduler_enabled": True}
        ):
            with patch("openviper.tasks.broker.logger") as mock_logger:
                with patch.dict("sys.modules", {"openviper.tasks.middleware": None}):
                    _create_broker()

        assert any(
            "Could not" in str(c) or "SchedulerMiddleware" in str(c)
            for c in mock_logger.warning.call_args_list
        )

    @patch("openviper.tasks.broker.dramatiq.set_broker")
    @patch("openviper.tasks.broker._make_redis_broker")
    def test_cleanup_task_exception_logged(self, mock_redis, mock_set_broker):
        """Exception setting up cleanup task is caught and logged (lines 162-167)."""
        mock_redis.return_value = MagicMock()

        with patch(
            "openviper.tasks.broker._read_task_settings", return_value={"cleanup_enabled": True}
        ):
            with patch("openviper.tasks.broker.logger") as mock_logger:
                with patch.dict("sys.modules", {"openviper.tasks.results": None}):
                    _create_broker()

        assert any("cleanup" in str(c).lower() for c in mock_logger.warning.call_args_list)

    @patch("openviper.tasks.broker.dramatiq.set_broker")
    @patch("openviper.tasks.broker._make_redis_broker")
    def test_backend_url_exception_logged(self, mock_redis, mock_set_broker):
        """Exception attaching result backend is caught and logged (lines 172-183)."""
        mock_redis.return_value = MagicMock()

        with patch(
            "openviper.tasks.broker._read_task_settings",
            return_value={"backend_url": "redis://localhost:6379"},
        ):
            with patch("openviper.tasks.broker.logger") as mock_logger:
                with patch.dict(
                    "sys.modules",
                    {"dramatiq.results": None, "dramatiq.results.backends.redis": None},
                ):
                    _create_broker()

        assert any(
            "result backend" in str(c).lower() or "Could not" in str(c)
            for c in mock_logger.warning.call_args_list
        )


class TestCreateBrokerSuccessPaths:
    """Test _create_broker success paths (lines 165, 174-178)."""

    @patch("openviper.tasks.broker.dramatiq.set_broker")
    @patch("openviper.tasks.broker._make_redis_broker")
    def test_cleanup_task_setup_success(self, mock_redis, mock_set_broker):
        """setup_cleanup_task() is called when cleanup_enabled=True (line 165)."""
        mock_redis.return_value = MagicMock()

        mock_setup = MagicMock()
        with patch(
            "openviper.tasks.broker._read_task_settings", return_value={"cleanup_enabled": True}
        ):
            with patch.dict(
                "sys.modules", {"openviper.tasks.results": MagicMock(setup_cleanup_task=mock_setup)}
            ):
                _create_broker()

        mock_setup.assert_called_once()

    @patch("openviper.tasks.broker.dramatiq.set_broker")
    @patch("openviper.tasks.broker._make_redis_broker")
    def test_backend_url_success_logs_host(self, mock_redis, mock_set_broker):
        """Result backend attaches successfully and logs host info (lines 174-178)."""
        mock_broker = MagicMock()
        mock_redis.return_value = mock_broker

        mock_results_cls = MagicMock()
        mock_redis_backend_cls = MagicMock()
        mock_results_module = MagicMock()
        mock_results_module.Results = mock_results_cls

        mock_backend_module = MagicMock()
        mock_backend_module.RedisBackend = mock_redis_backend_cls

        with patch(
            "openviper.tasks.broker._read_task_settings",
            return_value={"backend_url": "redis://localhost:6379"},
        ):
            with patch("openviper.tasks.broker.logger") as mock_logger:
                with patch.dict(
                    "sys.modules",
                    {
                        "dramatiq.results": mock_results_module,
                        "dramatiq.results.backends": MagicMock(),
                        "dramatiq.results.backends.redis": mock_backend_module,
                    },
                ):
                    _create_broker()

        # logger.info was called with the backend host info
        assert mock_broker.add_middleware.called
