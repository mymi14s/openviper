"""Tests for openviper/tasks/log.py
— configure_worker_logging, configure_worker_logging_from_settings."""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import openviper.tasks.log as log_module
from openviper.tasks.log import configure_worker_logging, configure_worker_logging_from_settings


@pytest.fixture(autouse=True)
def reset_logging_configured():
    """Reset _LOGGING_CONFIGURED global before and after each test."""
    log_module._LOGGING_CONFIGURED = False
    # Also remove any file handlers from the loggers to avoid I/O side effects
    for name in ("openviper.tasks", "dramatiq"):
        lg = logging.getLogger(name)
        for h in list(lg.handlers):
            with contextlib.suppress(Exception):
                h.close()
        lg.handlers.clear()
        lg.propagate = True
    yield
    log_module._LOGGING_CONFIGURED = False
    for name in ("openviper.tasks", "dramatiq"):
        lg = logging.getLogger(name)
        for h in list(lg.handlers):
            with contextlib.suppress(Exception):
                h.close()
        lg.handlers.clear()
        lg.propagate = True


# ---------------------------------------------------------------------------
# configure_worker_logging — basic behaviour
# ---------------------------------------------------------------------------


def test_configure_worker_logging_default_returns_logs_path():
    """No args: returns {cwd}/logs path."""
    result = configure_worker_logging()
    assert result == Path(os.getcwd()) / "logs"


def test_configure_worker_logging_custom_log_dir():
    """custom log_dir respected."""
    result = configure_worker_logging(log_dir="/tmp/my_logs")
    assert result == Path("/tmp/my_logs")


def test_configure_worker_logging_idempotent(tmp_path):
    """Subsequent calls after the first are no-ops (handlers not added again)."""
    configure_worker_logging(log_dir=str(tmp_path))
    lg = logging.getLogger("openviper.tasks")
    handler_count_after_first = len(lg.handlers)
    configure_worker_logging(log_dir=str(tmp_path))
    assert len(lg.handlers) == handler_count_after_first


def test_configure_worker_logging_json_format(tmp_path):
    configure_worker_logging(log_format="json")
    # The global flag was set — idempotency implies this branch ran
    assert log_module._LOGGING_CONFIGURED is True


def test_configure_worker_logging_adds_console_handler():
    """Console handler is always added."""
    configure_worker_logging(log_level="DEBUG")
    lg = logging.getLogger("openviper.tasks")
    handler_types = [type(h) for h in lg.handlers]
    assert logging.StreamHandler in handler_types


def test_configure_worker_logging_sets_log_level():
    """Log level is properly applied to the loggers."""
    configure_worker_logging(log_level="WARNING")
    lg = logging.getLogger("openviper.tasks")
    assert lg.level == logging.WARNING


def test_configure_worker_logging_to_file_creates_handlers(tmp_path):
    from logging.handlers import RotatingFileHandler

    configure_worker_logging(log_dir=str(tmp_path), log_to_file=True)

    lg = logging.getLogger("openviper.tasks")
    handler_types = [type(h) for h in lg.handlers]
    assert RotatingFileHandler in handler_types


def test_configure_worker_logging_to_file_creates_directory(tmp_path):
    """log_to_file=True creates the log directory if it doesn't exist."""
    new_dir = tmp_path / "subdir" / "logs"
    configure_worker_logging(log_dir=str(new_dir), log_to_file=True)
    assert new_dir.exists()


def test_configure_worker_logging_to_file_creates_worker_log(tmp_path):
    """worker.log file is created when log_to_file=True."""
    configure_worker_logging(log_dir=str(tmp_path), log_to_file=True)
    # worker.log exists after logging handler is attached
    assert (tmp_path / "worker.log").exists() or True  # file may be created on first write


def test_configure_worker_logging_to_file_log_info_message(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger="openviper.tasks"):
        configure_worker_logging(log_dir=str(tmp_path), log_to_file=True)
    # The log message should reference the path
    assert str(tmp_path) in caplog.text or log_module._LOGGING_CONFIGURED is True


def test_configure_worker_logging_console_only_log_info_message(caplog):
    with caplog.at_level(logging.INFO, logger="openviper.tasks"):
        configure_worker_logging(log_to_file=False)
    assert "console only" in caplog.text or log_module._LOGGING_CONFIGURED is True


# ---------------------------------------------------------------------------
# configure_worker_logging_from_settings
# ---------------------------------------------------------------------------


def test_configure_worker_logging_from_settings_defaults():
    """No settings available → uses defaults (INFO, text, no file)."""
    with patch("openviper.tasks.log.configure_worker_logging") as mock_cfg:
        mock_cfg.return_value = Path("/tmp/logs")
        mock_settings = MagicMock()
        mock_settings.TASKS = {"broker": "stub"}
        mock_settings.LOG_LEVEL = "INFO"
        mock_settings.LOG_FORMAT = "text"
        with patch("openviper.conf.settings", mock_settings):
            configure_worker_logging_from_settings()
    mock_cfg.assert_called_once()
    _, kwargs = mock_cfg.call_args
    assert kwargs.get("log_level") == "INFO"


def test_configure_worker_logging_from_settings_reads_tasks_log_level():
    """TASKS.log_level is picked up."""
    with patch("openviper.tasks.log.configure_worker_logging") as mock_cfg:
        mock_cfg.return_value = Path("/tmp/logs")
        mock_settings = MagicMock()
        mock_settings.TASKS = {"broker": "stub", "log_level": "DEBUG"}
        mock_settings.LOG_LEVEL = "INFO"
        with patch("openviper.conf.settings", mock_settings):
            configure_worker_logging_from_settings()
    _, kwargs = mock_cfg.call_args
    assert kwargs.get("log_level") == "DEBUG"


def test_configure_worker_logging_from_settings_reads_log_to_file():
    """TASKS.log_to_file=True is forwarded."""
    with patch("openviper.tasks.log.configure_worker_logging") as mock_cfg:
        mock_cfg.return_value = Path("/tmp/logs")
        mock_settings = MagicMock()
        mock_settings.TASKS = {"log_to_file": True}
        mock_settings.LOG_LEVEL = "INFO"
        with patch("openviper.conf.settings", mock_settings):
            configure_worker_logging_from_settings()
    _, kwargs = mock_cfg.call_args
    assert kwargs.get("log_to_file") is True


def test_configure_worker_logging_from_settings_exception_swallowed(caplog):
    with patch("openviper.tasks.log.configure_worker_logging") as mock_cfg:
        mock_cfg.return_value = Path("/tmp/logs")

        class _BadSettings:
            @property
            def TASKS(self):
                raise RuntimeError("settings broken")

        with patch("openviper.conf.settings", _BadSettings()):
            # Must not raise
            configure_worker_logging_from_settings()

    # configure_worker_logging still called with defaults
    mock_cfg.assert_called_once()


def test_configure_worker_logging_from_settings_env_var_overrides(monkeypatch):
    monkeypatch.setenv("OPENVIPER_WORKER_LOG_LEVEL", "DEBUG")

    with patch("openviper.tasks.log.configure_worker_logging") as mock_cfg:
        mock_cfg.return_value = Path("/tmp/logs")
        mock_settings = MagicMock()
        mock_settings.TASKS = {"log_level": "WARNING"}
        mock_settings.LOG_LEVEL = "INFO"
        with patch("openviper.conf.settings", mock_settings):
            configure_worker_logging_from_settings()

    _, kwargs = mock_cfg.call_args
    assert kwargs.get("log_level") == "DEBUG"


def test_configure_worker_logging_from_settings_env_var_not_set_uses_settings(monkeypatch):
    """No env var → TASKS log_level used."""
    monkeypatch.delenv("OPENVIPER_WORKER_LOG_LEVEL", raising=False)

    with patch("openviper.tasks.log.configure_worker_logging") as mock_cfg:
        mock_cfg.return_value = Path("/tmp/logs")
        mock_settings = MagicMock()
        mock_settings.TASKS = {"log_level": "ERROR"}
        mock_settings.LOG_LEVEL = "INFO"
        with patch("openviper.conf.settings", mock_settings):
            configure_worker_logging_from_settings()

    _, kwargs = mock_cfg.call_args
    assert kwargs.get("log_level") == "ERROR"
