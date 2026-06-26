"""Tests for openviper.tasks.broker - broker factory."""

from __future__ import annotations

import contextlib
from unittest.mock import patch

import pytest

from openviper.tasks.broker import SUPPORTED_BROKERS, get_broker, reset_broker
from openviper.tasks.exceptions import OpenViperTasksConfigurationError


class TestGetBroker:
    """Test broker factory."""

    def setup_method(self) -> None:
        reset_broker()

    def teardown_method(self) -> None:
        reset_broker()

    def test_missing_broker_url_raises_for_redis(self) -> None:
        with patch("openviper.tasks.broker.settings") as mock_settings:
            mock_settings.TASKS = {"enabled": 1, "broker": "redis", "broker_url": ""}
            with pytest.raises(OpenViperTasksConfigurationError, match="broker_url"):
                get_broker()

    def test_missing_broker_url_raises_for_rabbitmq(self) -> None:
        with patch("openviper.tasks.broker.settings") as mock_settings:
            mock_settings.TASKS = {"enabled": 1, "broker": "rabbitmq", "broker_url": ""}
            with pytest.raises(OpenViperTasksConfigurationError, match="broker_url"):
                get_broker()

    def test_unsupported_broker_type_raises(self) -> None:
        with patch("openviper.tasks.broker.settings") as mock_settings:
            mock_settings.TASKS = {
                "enabled": 1,
                "broker": "kafka",
                "broker_url": "kafka://localhost",
            }
            with pytest.raises(OpenViperTasksConfigurationError, match="Unsupported broker"):
                get_broker()

    def test_supported_brokers_contains_all_types(self) -> None:
        assert {"redis", "rabbitmq", "sqs", "stub"} == SUPPORTED_BROKERS

    def test_stub_broker_creates_successfully(self) -> None:
        with patch("openviper.tasks.broker.settings") as mock_settings:
            mock_settings.TASKS = {"enabled": 1, "broker": "stub"}
            broker = get_broker()
            assert broker is not None
            reset_broker()

    def test_stub_broker_does_not_require_broker_url(self) -> None:
        with patch("openviper.tasks.broker.settings") as mock_settings:
            mock_settings.TASKS = {"enabled": 1, "broker": "stub", "broker_url": ""}
            broker = get_broker()
            assert broker is not None
            reset_broker()

    def test_sqs_broker_does_not_require_broker_url(self) -> None:
        with patch("openviper.tasks.broker.settings") as mock_settings:
            mock_settings.TASKS = {"enabled": 1, "broker": "sqs", "broker_url": ""}
            with patch("openviper.tasks.broker.dramatiq_sqs") as mock_sqs:
                mock_sqs.SQSBroker.return_value = type("FakeBroker", (), {})()
                with patch("openviper.tasks.broker.dramatiq") as mock_dramatiq:
                    mock_dramatiq.set_broker.return_value = None
                    with contextlib.suppress(Exception):
                        get_broker()
                    reset_broker()

    def test_redis_broker_missing_package_raises(self) -> None:
        with patch("openviper.tasks.broker.settings") as mock_settings:
            mock_settings.TASKS = {
                "enabled": 1,
                "broker": "redis",
                "broker_url": "redis://localhost:6379",
            }
            with patch("openviper.tasks.broker.dramatiq.brokers.redis", None):
                with pytest.raises(OpenViperTasksConfigurationError, match="not installed"):
                    get_broker()

    def test_rabbitmq_broker_missing_package_raises(self) -> None:
        with patch("openviper.tasks.broker.settings") as mock_settings:
            mock_settings.TASKS = {
                "enabled": 1,
                "broker": "rabbitmq",
                "broker_url": "amqp://guest:guest@localhost:5672",
            }
            with patch("openviper.tasks.broker.dramatiq.brokers.rabbitmq", None):
                with pytest.raises(OpenViperTasksConfigurationError, match="not installed"):
                    get_broker()

    def test_sqs_broker_missing_package_raises(self) -> None:
        with patch("openviper.tasks.broker.settings") as mock_settings:
            mock_settings.TASKS = {"enabled": 1, "broker": "sqs"}
            with patch("openviper.tasks.broker.dramatiq_sqs", None):
                with pytest.raises(OpenViperTasksConfigurationError, match="not installed"):
                    get_broker()
