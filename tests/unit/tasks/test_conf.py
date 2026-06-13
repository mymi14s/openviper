"""Tests for openviper.tasks.conf - configuration validation."""

from __future__ import annotations

import pytest

from openviper.tasks.conf import resolve_tasks_config, validate_tasks_config
from openviper.tasks.exceptions import OpenViperTasksConfigurationError


class TestValidateTasksConfig:
    """Test TASKS configuration validation."""

    def test_valid_minimal_config(self) -> None:
        cfg = {"enabled": 1, "broker": "redis", "broker_url": "redis://localhost:6379"}
        validate_tasks_config(cfg)

    def test_disabled_config_skips_broker_url_check(self) -> None:
        cfg = {"enabled": 0, "broker": "redis", "broker_url": ""}
        validate_tasks_config(cfg)

    def test_invalid_enabled_value_raises(self) -> None:
        cfg = {"enabled": 2, "broker": "redis", "broker_url": "redis://localhost"}
        with pytest.raises(OpenViperTasksConfigurationError) as exc_info:
            validate_tasks_config(cfg)
        assert "enabled" in str(exc_info.value).lower()

    def test_invalid_broker_type_raises(self) -> None:
        cfg = {"enabled": 1, "broker": "kafka", "broker_url": "kafka://localhost"}
        with pytest.raises(OpenViperTasksConfigurationError) as exc_info:
            validate_tasks_config(cfg)
        assert "broker" in str(exc_info.value).lower()

    def test_missing_broker_url_when_enabled_raises(self) -> None:
        cfg = {"enabled": 1, "broker": "redis", "broker_url": ""}
        with pytest.raises(OpenViperTasksConfigurationError) as exc_info:
            validate_tasks_config(cfg)
        assert "broker_url" in str(exc_info.value).lower()

    def test_invalid_log_format_raises(self) -> None:
        cfg = {
            "enabled": 1,
            "broker": "redis",
            "broker_url": "redis://localhost",
            "logging": {"file": {"log_format": "xml"}},
        }
        with pytest.raises(OpenViperTasksConfigurationError):
            validate_tasks_config(cfg)

    def test_invalid_max_size_raises(self) -> None:
        cfg = {
            "enabled": 1,
            "broker": "redis",
            "broker_url": "redis://localhost",
            "logging": {"file": {"max_size": -1}},
        }
        with pytest.raises(OpenViperTasksConfigurationError) as exc_info:
            validate_tasks_config(cfg)
        assert "max_size" in str(exc_info.value).lower()

    def test_invalid_database_task_value_raises(self) -> None:
        cfg = {
            "enabled": 1,
            "broker": "redis",
            "broker_url": "redis://localhost",
            "logging": {"database": {"task": 2}},
        }
        with pytest.raises(OpenViperTasksConfigurationError) as exc_info:
            validate_tasks_config(cfg)
        assert "task" in str(exc_info.value).lower()

    def test_invalid_database_periodic_value_raises(self) -> None:
        cfg = {
            "enabled": 1,
            "broker": "redis",
            "broker_url": "redis://localhost",
            "logging": {"database": {"periodic": 3}},
        }
        with pytest.raises(OpenViperTasksConfigurationError) as exc_info:
            validate_tasks_config(cfg)
        assert "periodic" in str(exc_info.value).lower()

    def test_database_task_zero_is_valid(self) -> None:
        cfg = {
            "enabled": 1,
            "broker": "redis",
            "broker_url": "redis://localhost",
            "logging": {"database": {"task": 0}},
        }
        validate_tasks_config(cfg)

    def test_database_disabled_with_zero(self) -> None:
        cfg = {
            "enabled": 1,
            "broker": "redis",
            "broker_url": "redis://localhost",
            "logging": {"database": 0},
        }
        validate_tasks_config(cfg)

    def test_file_disabled_with_zero(self) -> None:
        cfg = {
            "enabled": 1,
            "broker": "redis",
            "broker_url": "redis://localhost",
            "logging": {"file": 0},
        }
        validate_tasks_config(cfg)

    def test_non_dict_raises(self) -> None:
        with pytest.raises(OpenViperTasksConfigurationError):
            validate_tasks_config("not a dict")  # type: ignore[arg-type]


class TestResolveTasksConfig:
    """Test configuration merging and defaults."""

    def test_defaults_applied_for_missing_keys(self) -> None:
        cfg = resolve_tasks_config(
            {"enabled": 1, "broker": "redis", "broker_url": "redis://localhost"}
        )
        assert cfg["enabled"] == 1
        assert cfg["logging"]["level"] == "INFO"
        assert cfg["logging"]["file"] is None
        assert cfg["logging"]["database"] is None

    def test_logging_dict_merged(self) -> None:
        cfg = resolve_tasks_config(
            {
                "enabled": 1,
                "broker": "redis",
                "broker_url": "redis://localhost",
                "logging": {"level": "DEBUG"},
            }
        )
        assert cfg["logging"]["level"] == "DEBUG"
        assert cfg["logging"]["file"] is None
        assert cfg["logging"]["database"] is None

    def test_file_dict_used_as_is(self) -> None:
        cfg = resolve_tasks_config(
            {
                "enabled": 1,
                "broker": "redis",
                "broker_url": "redis://localhost",
                "logging": {"file": {"max_size": 50, "file_name": "tasks.log"}},
            }
        )
        assert cfg["logging"]["file"]["max_size"] == 50
        assert cfg["logging"]["file"]["file_name"] == "tasks.log"

    def test_database_dict_used_as_is(self) -> None:
        cfg = resolve_tasks_config(
            {
                "enabled": 1,
                "broker": "redis",
                "broker_url": "redis://localhost",
                "logging": {"database": {"task": 1, "periodic": 0}},
            }
        )
        assert cfg["logging"]["database"]["task"] == 1
        assert cfg["logging"]["database"]["periodic"] == 0

    def test_file_none_means_disabled(self) -> None:
        cfg = resolve_tasks_config(
            {
                "enabled": 1,
                "broker": "redis",
                "broker_url": "redis://localhost",
                "logging": {"file": None},
            }
        )
        assert cfg["logging"]["file"] is None

    def test_database_none_means_disabled(self) -> None:
        cfg = resolve_tasks_config(
            {
                "enabled": 1,
                "broker": "redis",
                "broker_url": "redis://localhost",
                "logging": {"database": None},
            }
        )
        assert cfg["logging"]["database"] is None

    def test_none_returns_defaults(self) -> None:
        cfg = resolve_tasks_config({"enabled": 0})
        assert cfg["enabled"] == 0
        assert cfg["broker"] == "redis"
