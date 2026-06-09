"""Tests for openviper.tasks.logging - task logging configuration."""

from __future__ import annotations

import json
import logging

import pytest

from openviper.tasks.logging import configure_task_logging, get_task_logger
from openviper.utils.logging import ConcurrentRotatingFileHandler


class TestGetTaskLogger:
    """Test task logger creation."""

    def test_returns_named_logger(self) -> None:
        logger = get_task_logger("openviper.tasks.test")
        assert logger.name == "openviper.tasks.test"

    def test_logger_under_task_hierarchy(self) -> None:
        logger = get_task_logger("openviper.tasks.custom")
        assert logger.name.startswith("openviper.tasks")

    def test_logger_propagate_is_false(self) -> None:
        """Task loggers must not propagate to the root logger to prevent
        output leakage into the web-server process."""
        logger = get_task_logger("openviper.tasks.isolation_test")
        assert logger.propagate is False


class TestConfigureTaskLogging:
    """Test file-based task logging setup."""

    @pytest.fixture(autouse=True)
    def _cleanup_logging(self) -> None:
        """Reset task logging state and clean up handlers between tests."""
        import openviper.tasks.logging as log_mod

        root_logger = logging.getLogger()
        ov_logger = logging.getLogger("openviper")
        task_logger = logging.getLogger("openviper.tasks")

        root_handlers_before = list(root_logger.handlers)
        ov_level_before = ov_logger.level
        task_handlers_before = list(task_logger.handlers)
        task_propagate_before = task_logger.propagate

        log_mod.TASK_LOGGING_CONFIGURED = False
        log_mod.WORKER_MODE = False

        yield

        root_logger.handlers = root_handlers_before
        ov_logger.setLevel(ov_level_before)
        task_logger.handlers = task_handlers_before
        task_logger.propagate = task_propagate_before
        log_mod.TASK_LOGGING_CONFIGURED = False
        log_mod.WORKER_MODE = False

    def test_creates_concurrent_rotating_file_handler(self, tmp_path) -> None:
        """configure_task_logging must use ConcurrentRotatingFileHandler."""
        cfg = {
            "logging": {
                "level": "DEBUG",
                "file": {
                    "file_name": "test_tasks.log",
                    "log_dir": str(tmp_path),
                    "log_format": "text",
                    "rotate_log_file": 1,
                    "max_size": 1,
                },
                "database": {"task": 1, "periodic": 1},
            },
        }
        configure_task_logging(cfg)

        root = logging.getLogger("openviper.tasks")
        concurrent_handlers = [
            h for h in root.handlers if isinstance(h, ConcurrentRotatingFileHandler)
        ]
        assert len(concurrent_handlers) >= 1

    def test_json_log_output_to_file(self, tmp_path) -> None:
        """Verify disk serialization outputs to the configured path."""
        cfg = {
            "logging": {
                "level": "DEBUG",
                "file": {
                    "file_name": "json_test.log",
                    "log_dir": str(tmp_path),
                    "log_format": "json",
                    "rotate_log_file": 1,
                    "max_size": 1,
                },
                "database": {"task": 1, "periodic": 1},
            },
        }
        configure_task_logging(cfg)

        root_task_logger = logging.getLogger("openviper.tasks")
        root_task_logger.info("test json message")

        log_file = tmp_path / "json_test.log"
        assert log_file.exists()

    def test_root_task_logger_propagate_false(self, tmp_path) -> None:
        """The root task logger must not propagate to prevent web-server leakage."""
        cfg = {
            "logging": {
                "level": "INFO",
                "file": {
                    "file_name": "propagate_test.log",
                    "log_dir": str(tmp_path),
                    "log_format": "text",
                    "rotate_log_file": 1,
                    "max_size": 1,
                },
                "database": {"task": 1, "periodic": 1},
            },
        }
        configure_task_logging(cfg)

        root = logging.getLogger("openviper.tasks")
        assert root.propagate is False

    def test_worker_mode_adds_handler_to_root_logger(self, tmp_path) -> None:
        """When worker_mode=True, the file handler is attached to the
        root logger so that application task module logs are captured."""
        cfg = {
            "logging": {
                "level": "INFO",
                "file": {
                    "file_name": "worker_test.log",
                    "log_dir": str(tmp_path),
                    "log_format": "text",
                    "rotate_log_file": 1,
                    "max_size": 1,
                },
                "database": {"task": 1, "periodic": 1},
            },
        }
        configure_task_logging(cfg, worker_mode=True)

        root_logger = logging.getLogger()
        concurrent_handlers = [
            h for h in root_logger.handlers if isinstance(h, ConcurrentRotatingFileHandler)
        ]
        assert len(concurrent_handlers) >= 1

    def test_worker_mode_propagate_true(self, tmp_path) -> None:
        """When worker_mode=True, openviper.tasks propagate is re-enabled
        so that task records reach the root logger and its handlers."""
        cfg = {
            "logging": {
                "level": "INFO",
                "file": {
                    "file_name": "propagate_worker_test.log",
                    "log_dir": str(tmp_path),
                    "log_format": "text",
                    "rotate_log_file": 1,
                    "max_size": 1,
                },
                "database": {"task": 1, "periodic": 1},
            },
        }
        configure_task_logging(cfg, worker_mode=True)

        root_task = logging.getLogger("openviper.tasks")
        assert root_task.propagate is True

    def test_worker_mode_no_handler_on_task_logger(self, tmp_path) -> None:
        """When worker_mode=True, the file handler is on the root logger,
        not on openviper.tasks, to avoid duplicate log entries."""
        cfg = {
            "logging": {
                "level": "INFO",
                "file": {
                    "file_name": "no_dup_test.log",
                    "log_dir": str(tmp_path),
                    "log_format": "text",
                    "rotate_log_file": 1,
                    "max_size": 1,
                },
                "database": {"task": 1, "periodic": 1},
            },
        }
        configure_task_logging(cfg, worker_mode=True)

        root_task = logging.getLogger("openviper.tasks")
        concurrent_on_task = [
            h for h in root_task.handlers if isinstance(h, ConcurrentRotatingFileHandler)
        ]
        assert len(concurrent_on_task) == 0

        root_logger = logging.getLogger()
        concurrent_on_root = [
            h for h in root_logger.handlers if isinstance(h, ConcurrentRotatingFileHandler)
        ]
        assert len(concurrent_on_root) >= 1

    def test_non_worker_mode_does_not_add_handler_to_root_logger(self, tmp_path) -> None:
        """When worker_mode=False (default), the root logger must not receive
        the task file handler to prevent web-server log pollution."""
        root_before = logging.getLogger()
        handlers_before = len(root_before.handlers)

        cfg = {
            "logging": {
                "level": "INFO",
                "file": {
                    "file_name": "non_worker_test.log",
                    "log_dir": str(tmp_path),
                    "log_format": "text",
                    "rotate_log_file": 1,
                    "max_size": 1,
                },
                "database": {"task": 1, "periodic": 1},
            },
        }
        configure_task_logging(cfg, worker_mode=False)

        root_after = logging.getLogger()
        assert len(root_after.handlers) == handlers_before

    def test_non_worker_mode_handler_on_task_logger(self, tmp_path) -> None:
        """When worker_mode=False, the file handler is on openviper.tasks
        so that task logs are captured without polluting the root logger."""
        cfg = {
            "logging": {
                "level": "INFO",
                "file": {
                    "file_name": "non_worker_handler_test.log",
                    "log_dir": str(tmp_path),
                    "log_format": "text",
                    "rotate_log_file": 1,
                    "max_size": 1,
                },
                "database": {"task": 1, "periodic": 1},
            },
        }
        configure_task_logging(cfg, worker_mode=False)

        root_task = logging.getLogger("openviper.tasks")
        concurrent_on_task = [
            h for h in root_task.handlers if isinstance(h, ConcurrentRotatingFileHandler)
        ]
        assert len(concurrent_on_task) >= 1

    def test_worker_mode_adds_console_handler(self, tmp_path) -> None:
        """When worker_mode=True, a console handler is added to the root
        logger so that startup messages are visible on stderr."""
        cfg = {
            "logging": {
                "level": "INFO",
                "file": {
                    "file_name": "console_test.log",
                    "log_dir": str(tmp_path),
                    "log_format": "text",
                    "rotate_log_file": 1,
                    "max_size": 1,
                },
                "database": {"task": 1, "periodic": 1},
            },
        }
        configure_task_logging(cfg, worker_mode=True)

        root_logger = logging.getLogger()
        stream_handlers = [
            h
            for h in root_logger.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, ConcurrentRotatingFileHandler)
        ]
        assert len(stream_handlers) >= 1

    def test_worker_mode_get_task_logger_propagate_true(self, tmp_path) -> None:
        """When worker_mode=True, loggers created via get_task_logger after
        configure_task_logging must have propagate=True so that records
        from middleware and other late-imported modules reach the root logger."""
        cfg = {
            "logging": {
                "level": "INFO",
                "file": {
                    "file_name": "late_logger_test.log",
                    "log_dir": str(tmp_path),
                    "log_format": "text",
                    "rotate_log_file": 1,
                    "max_size": 1,
                },
                "database": {"task": 1, "periodic": 1},
            },
        }
        configure_task_logging(cfg, worker_mode=True)

        # Simulate a module that calls get_task_logger AFTER
        # configure_task_logging (e.g. middleware imported at worker startup).
        late_logger = get_task_logger("openviper.tasks.late_module")
        assert late_logger.propagate is True

    def test_non_worker_mode_get_task_logger_propagate_false(self, tmp_path) -> None:
        """When worker_mode=False, loggers created via get_task_logger must
        have propagate=False to prevent task output leaking into the
        web-server process log stream."""
        cfg = {
            "logging": {
                "level": "INFO",
                "file": {
                    "file_name": "late_logger_nonworker_test.log",
                    "log_dir": str(tmp_path),
                    "log_format": "text",
                    "rotate_log_file": 1,
                    "max_size": 1,
                },
                "database": {"task": 1, "periodic": 1},
            },
        }
        configure_task_logging(cfg, worker_mode=False)

        late_logger = get_task_logger("openviper.tasks.late_nonworker")
        assert late_logger.propagate is False

    def test_worker_mode_lowers_openviper_logger_level(self, tmp_path) -> None:
        """When worker_mode=True, the openviper logger level is lowered
        to the task logging level so that records from loggers under
        openviper (e.g. openviper.email) reach the root logger."""
        ov_logger = logging.getLogger("openviper")
        original_level = ov_logger.level
        ov_logger.setLevel(logging.WARNING)

        cfg = {
            "logging": {
                "level": "INFO",
                "file": {
                    "file_name": "level_test.log",
                    "log_dir": str(tmp_path),
                    "log_format": "text",
                    "rotate_log_file": 1,
                    "max_size": 1,
                },
                "database": {"task": 1, "periodic": 1},
            },
        }
        configure_task_logging(cfg, worker_mode=True)

        assert ov_logger.level <= logging.INFO

        ov_logger.setLevel(original_level or logging.WARNING)
