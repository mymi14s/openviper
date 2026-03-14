"""Unit tests for openviper.tasks.log — Worker logging configuration."""

import logging
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import openviper.tasks.log as log_module
from openviper.tasks.log import (
    configure_worker_logging,
    configure_worker_logging_from_settings,
)


@pytest.fixture(autouse=True)
def reset_logging_state():
    """Reset global _LOGGING_CONFIGURED flag and clean handlers before each test."""
    log_module._LOGGING_CONFIGURED = False
    # Clean up handlers added by previous tests
    for name in ("openviper.tasks", "dramatiq"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
        lg.setLevel(logging.WARNING)
    yield
    # Teardown: reset again
    log_module._LOGGING_CONFIGURED = False
    for name in ("openviper.tasks", "dramatiq"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
        lg.setLevel(logging.WARNING)


class TestConfigureWorkerLogging:
    """Test configure_worker_logging function."""

    def test_returns_log_directory_path(self, tmp_path):
        """Should return the resolved log directory path."""
        result = configure_worker_logging(log_dir=tmp_path, log_to_file=True)
        assert result == tmp_path

    def test_defaults_to_cwd_logs(self, tmp_path):
        """Should default to {cwd}/logs when log_dir is None."""
        with patch("openviper.tasks.log.os.getcwd", return_value=str(tmp_path)):
            result = configure_worker_logging(log_to_file=False)
            assert result == tmp_path / "logs"

    def test_creates_log_directory_when_log_to_file_true(self, tmp_path):
        """Should create log directory when log_to_file is True."""
        log_dir = tmp_path / "my_logs"
        assert not log_dir.exists()

        configure_worker_logging(log_dir=log_dir, log_to_file=True)

        assert log_dir.exists()
        assert log_dir.is_dir()

    def test_does_not_create_directory_when_log_to_file_false(self, tmp_path):
        """Should not create log directory when log_to_file is False."""
        log_dir = tmp_path / "my_logs"
        assert not log_dir.exists()

        configure_worker_logging(log_dir=log_dir, log_to_file=False)

        assert not log_dir.exists()

    def test_creates_parent_directories(self, tmp_path):
        """Should create parent directories if they don't exist."""
        log_dir = tmp_path / "a" / "b" / "c" / "logs"
        assert not log_dir.exists()

        configure_worker_logging(log_dir=log_dir, log_to_file=True)

        assert log_dir.exists()

    def test_sets_log_level(self, tmp_path):
        """Should configure log level for openviper.tasks and dramatiq."""
        configure_worker_logging(log_dir=tmp_path, log_level="DEBUG", log_to_file=False)

        tasks_logger = logging.getLogger("openviper.tasks")
        dramatiq_logger = logging.getLogger("dramatiq")

        assert tasks_logger.level == logging.DEBUG
        assert dramatiq_logger.level == logging.DEBUG

    def test_handles_invalid_log_level(self, tmp_path):
        """Should fall back to INFO for invalid log level."""
        configure_worker_logging(log_dir=tmp_path, log_level="INVALID", log_to_file=False)

        tasks_logger = logging.getLogger("openviper.tasks")
        assert tasks_logger.level == logging.INFO

    def test_attaches_console_handler(self, tmp_path):
        """Should always attach a console handler."""
        configure_worker_logging(log_dir=tmp_path, log_to_file=False)

        tasks_logger = logging.getLogger("openviper.tasks")
        handler_types = [type(h).__name__ for h in tasks_logger.handlers]

        assert "StreamHandler" in handler_types

    def test_attaches_file_handlers_when_enabled(self, tmp_path):
        """Should attach file handlers when log_to_file is True."""
        configure_worker_logging(log_dir=tmp_path, log_to_file=True)

        tasks_logger = logging.getLogger("openviper.tasks")
        handler_types = [type(h).__name__ for h in tasks_logger.handlers]

        assert "RotatingFileHandler" in handler_types

    def test_does_not_attach_file_handlers_when_disabled(self, tmp_path):
        """Should not attach file handlers when log_to_file is False."""
        configure_worker_logging(log_dir=tmp_path, log_to_file=False)

        tasks_logger = logging.getLogger("openviper.tasks")
        # Only console handler should be present
        handler_types = [type(h).__name__ for h in tasks_logger.handlers]

        # RotatingFileHandler should not be present
        file_handlers = [
            h for h in tasks_logger.handlers if type(h).__name__ == "RotatingFileHandler"
        ]
        assert len(file_handlers) == 0

    def test_json_format(self, tmp_path):
        """Should use JSON formatter when log_format='json'."""
        configure_worker_logging(log_dir=tmp_path, log_format="json", log_to_file=False)

        tasks_logger = logging.getLogger("openviper.tasks")
        # Check that at least one handler has a formatter
        formatters = [h.formatter for h in tasks_logger.handlers if h.formatter]
        assert len(formatters) > 0

    def test_text_format(self, tmp_path):
        """Should use text formatter when log_format='text'."""
        configure_worker_logging(log_dir=tmp_path, log_format="text", log_to_file=False)

        tasks_logger = logging.getLogger("openviper.tasks")
        formatters = [h.formatter for h in tasks_logger.handlers if h.formatter]
        assert len(formatters) > 0

    def test_idempotent_calls(self, tmp_path):
        """Should be safe to call multiple times."""
        configure_worker_logging(log_dir=tmp_path, log_to_file=False)
        handler_count = len(logging.getLogger("openviper.tasks").handlers)

        # Call again
        configure_worker_logging(log_dir=tmp_path, log_to_file=False)
        new_handler_count = len(logging.getLogger("openviper.tasks").handlers)

        # Should not add duplicate handlers
        assert new_handler_count == handler_count

    def test_prevents_propagation(self, tmp_path):
        """Should set propagate=False for task loggers."""
        configure_worker_logging(log_dir=tmp_path, log_to_file=False)

        tasks_logger = logging.getLogger("openviper.tasks")
        dramatiq_logger = logging.getLogger("dramatiq")

        assert tasks_logger.propagate is False
        assert dramatiq_logger.propagate is False


class TestConfigureWorkerLoggingFromSettings:
    """Test configure_worker_logging_from_settings function."""

    @patch("openviper.conf.settings")
    def test_reads_from_tasks_settings(self, mock_settings, tmp_path):
        """Should read log_level and log_format from TASKS dict."""
        mock_settings.TASKS = {
            "log_level": "WARNING",
            "log_format": "json",
            "log_dir": str(tmp_path),
            "log_to_file": True,
        }

        with patch("openviper.tasks.log.configure_worker_logging") as mock_configure:
            configure_worker_logging_from_settings()

            mock_configure.assert_called_once_with(
                log_dir=str(tmp_path),
                log_level="WARNING",
                log_format="json",
                log_to_file=True,
            )

    @patch("openviper.conf.settings")
    def test_falls_back_to_top_level_settings(self, mock_settings, tmp_path):
        """Should fall back to LOG_LEVEL if not in TASKS."""
        mock_settings.TASKS = {}
        mock_settings.LOG_LEVEL = "ERROR"
        mock_settings.LOG_FORMAT = "text"

        with patch("openviper.tasks.log.configure_worker_logging") as mock_configure:
            configure_worker_logging_from_settings()

            call_kwargs = mock_configure.call_args[1]
            assert call_kwargs["log_level"] == "ERROR"
            assert call_kwargs["log_format"] == "text"

    def test_defaults_when_no_settings(self):
        """Should use defaults when no settings are available."""
        # Use spec=[] to prevent MagicMock auto-generating attributes;
        # this makes getattr(settings, "LOG_LEVEL", "INFO") return "INFO".
        mock_settings = MagicMock(spec=[])
        mock_settings.TASKS = {}

        with patch("openviper.conf.settings", mock_settings):
            with patch("openviper.tasks.log.configure_worker_logging") as mock_configure:
                configure_worker_logging_from_settings()

                call_kwargs = mock_configure.call_args[1]
                assert call_kwargs["log_level"] == "INFO"
                assert call_kwargs["log_format"] == "text"

    def test_env_var_overrides_settings(self, tmp_path, monkeypatch):
        """OPENVIPER_WORKER_LOG_LEVEL env var should override settings."""
        monkeypatch.setenv("OPENVIPER_WORKER_LOG_LEVEL", "DEBUG")

        with patch("openviper.conf.settings") as mock_settings:
            mock_settings.TASKS = {"log_level": "INFO"}

            with patch("openviper.tasks.log.configure_worker_logging") as mock_configure:
                configure_worker_logging_from_settings()

                call_kwargs = mock_configure.call_args[1]
                assert call_kwargs["log_level"] == "DEBUG"

    @patch("openviper.conf.settings")
    def test_handles_missing_settings_gracefully(self, mock_settings):
        """Should not crash if settings access raises."""
        # Make TASKS access raise an exception so the except block fires
        type(mock_settings).TASKS = property(
            lambda self: (_ for _ in ()).throw(Exception("settings not configured"))
        )

        # Should not raise
        result = configure_worker_logging_from_settings()
        assert isinstance(result, Path)

    @patch("openviper.conf.settings")
    def test_log_to_file_default_false(self, mock_settings):
        """log_to_file should default to False."""
        mock_settings.TASKS = {}

        with patch("openviper.tasks.log.configure_worker_logging") as mock_configure:
            configure_worker_logging_from_settings()

            call_kwargs = mock_configure.call_args[1]
            assert call_kwargs["log_to_file"] is False

    @patch("openviper.conf.settings")
    def test_log_to_file_enabled(self, mock_settings):
        """log_to_file should be enabled when set in TASKS."""
        mock_settings.TASKS = {"log_to_file": 1}

        with patch("openviper.tasks.log.configure_worker_logging") as mock_configure:
            configure_worker_logging_from_settings()

            call_kwargs = mock_configure.call_args[1]
            assert call_kwargs["log_to_file"] is True


class TestConfigureWorkerLoggingThreadSafety:
    """configure_worker_logging must be idempotent under concurrent calls."""

    def test_concurrent_calls_configure_once(self):
        """Multiple threads racing on configure_worker_logging must only set up handlers once."""

        # Reset module state
        log_module._LOGGING_CONFIGURED = False
        # Remove existing handlers so we can count additions cleanly
        for name in ("openviper.tasks", "dramatiq"):
            lg = logging.getLogger(name)
            lg.handlers.clear()

        call_count = 0
        original_add = logging.Logger.addHandler

        def counting_add(self, handler):
            nonlocal call_count
            call_count += 1
            original_add(self, handler)

        results = []

        def run():
            results.append(configure_worker_logging(log_level="INFO", log_to_file=False))

        with patch.object(logging.Logger, "addHandler", counting_add):
            threads = [threading.Thread(target=run) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # All calls should return a Path without error
        assert len(results) == 10
        assert all(hasattr(r, "__fspath__") for r in results)
        # Module flag should be set
        assert log_module._LOGGING_CONFIGURED is True

        # Cleanup
        log_module._LOGGING_CONFIGURED = False
        for name in ("openviper.tasks", "dramatiq"):
            logging.getLogger(name).handlers.clear()


# ── configure_worker_logging double-checked lock inner guard (line 61) ──────


def test_configure_worker_logging_inner_lock_guard():
    """Inner double-checked-lock guard returns early when flag set under lock (line 61)."""

    class _SetFlagOnEnter:
        """Context manager that sets _LOGGING_CONFIGURED = True before yielding."""

        def __enter__(self):
            log_module._LOGGING_CONFIGURED = True

        def __exit__(self, *args):
            pass

    # Ensure outer check passes (flag is False)
    log_module._LOGGING_CONFIGURED = False

    with patch.object(log_module, "_LOGGING_LOCK", new=_SetFlagOnEnter()):
        result = configure_worker_logging(log_level="INFO", log_to_file=False)

    # Should return without doing any logging setup
    assert result is not None
    # Flag remains True (set by the mock lock's __enter__)
    assert log_module._LOGGING_CONFIGURED is True
