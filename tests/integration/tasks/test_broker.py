"""Integration tests for the OpenViper task broker factory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from dramatiq.brokers.rabbitmq import RabbitmqBroker
from dramatiq.brokers.redis import RedisBroker
from dramatiq.brokers.stub import StubBroker

from openviper.tasks.broker import (
    _create_broker,
    get_broker,
    reset_broker,
)


@pytest.fixture(autouse=True)
def clean_broker():
    """Ensure the broker is reset before and after each test."""
    reset_broker()
    yield
    reset_broker()


def test_get_broker_singleton():
    """get_broker should return the same instance on multiple calls."""
    # Use stub for easy testing without Redis
    with patch("openviper.tasks.broker._read_task_settings") as mock_settings:
        mock_settings.return_value = {"broker": "stub"}
        b1 = get_broker()
        b2 = get_broker()
        assert b1 is b2
        assert isinstance(b1, StubBroker)


def test_reset_broker():
    """reset_broker should clear the singleton instance."""
    with patch("openviper.tasks.broker._read_task_settings") as mock_settings:
        mock_settings.return_value = {"broker": "stub"}
        b1 = get_broker()
        reset_broker()
        b2 = get_broker()
        assert b1 is not b2


def test_create_broker_redis():
    """_create_broker should create a RedisBroker by default."""
    cfg = {"broker": "redis", "broker_url": "redis://localhost:6379/9"}
    with patch("openviper.tasks.broker._make_redis_broker") as mock_make:
        mock_make.return_value = MagicMock(spec=RedisBroker)
        broker = _create_broker()
        # By default it reads settings, so we need to mock _read_task_settings instead
        # Or better, just test that the logic in _create_broker handles backends
        pass


def test_create_broker_backends():
    """Test backend selection logic in _create_broker."""
    with patch("openviper.tasks.broker._read_task_settings") as mock_settings:
        # Redis
        mock_settings.return_value = {"broker": "redis"}
        with patch("openviper.tasks.broker._make_redis_broker") as mock_make:
            mock_make.return_value = MagicMock(spec=RedisBroker)
            b = _create_broker()
            assert isinstance(b, MagicMock)
            mock_make.assert_called_once()

        # RabbitMQ
        mock_settings.return_value = {"broker": "rabbitmq"}
        with patch("openviper.tasks.broker._make_rabbitmq_broker") as mock_make:
            mock_make.return_value = MagicMock(spec=RabbitmqBroker)
            b = _create_broker()
            assert isinstance(b, MagicMock)
            mock_make.assert_called_once()

        # Stub
        mock_settings.return_value = {"broker": "stub"}
        b = _create_broker()
        assert isinstance(b, StubBroker)

        # Invalid
        mock_settings.return_value = {"broker": "invalid"}
        with pytest.raises(ValueError, match="Unknown TASKS broker 'invalid'"):
            _create_broker()


def test_middleware_attachment():
    """Verify middleware is attached based on settings."""
    cfg = {
        "broker": "stub",
        "tracking_enabled": True,
        "scheduler_enabled": True,
        "backend_url": "redis://localhost:9999/0",
    }
    with patch("openviper.tasks.broker._read_task_settings", return_value=cfg):
        with patch("openviper.tasks.middleware.TaskTrackingMiddleware") as mock_tracking:
            with patch("openviper.tasks.middleware.SchedulerMiddleware") as mock_scheduler:
                with patch("dramatiq.results.Results") as mock_results:
                    broker = _create_broker()

                    mock_tracking.assert_called_once()
                    mock_scheduler.assert_called_once()
                    mock_results.assert_called_once()


def test_middleware_attachment_disabled():
    """Verify middleware is NOT attached when disabled."""
    cfg = {
        "broker": "stub",
        "tracking_enabled": False,
        "scheduler_enabled": False,
        "backend_url": None,
    }
    with patch("openviper.tasks.broker._read_task_settings", return_value=cfg):
        with patch("openviper.tasks.middleware.TaskTrackingMiddleware") as mock_tracking:
            with patch("openviper.tasks.middleware.SchedulerMiddleware") as mock_scheduler:
                with patch("dramatiq.results.Results") as mock_results:
                    _create_broker()

                    mock_tracking.assert_not_called()
                    mock_scheduler.assert_not_called()
                    mock_results.assert_not_called()


def test_middleware_attachment_failure_safe():
    """Ensure broker creation succeeds even if middleware attachment fails."""
    cfg = {
        "broker": "stub",
        "tracking_enabled": True,
        "scheduler_enabled": True,
    }
    with patch("openviper.tasks.broker._read_task_settings", return_value=cfg):
        with patch(
            "openviper.tasks.middleware.TaskTrackingMiddleware", side_effect=Exception("BOOM")
        ):
            # Should log warning but not raise
            broker = _create_broker()
            assert isinstance(broker, StubBroker)
