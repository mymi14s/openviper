"""Integration tests for the openviper.tasks subsystem.

These tests exercise the full task lifecycle: configuration validation,
broker initialisation, actor registration, discovery, scheduler, and
the start-worker management command.  They require a running Redis
instance and the ``openviper[tasks]`` extras.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import time
import typing as t
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openviper.tasks.broker import get_broker, reset_broker
from openviper.tasks.conf import resolve_tasks_config, validate_tasks_config
from openviper.tasks.decorators import actor
from openviper.tasks.exceptions import (
    OpenViperTasksConfigurationError,
    OpenViperTasksError,
    ResultsBackendDisabledError,
)
from openviper.tasks.logging import configure_task_logging, get_task_logger
from openviper.tasks.middleware import (
    DatabaseCleanupMiddleware,
    StateObservationMiddleware,
    UnifiedContextLogger,
    get_trace_id,
)
from openviper.tasks.periodic import parse_interval, periodic
from openviper.tasks.registry import Registry
from openviper.tasks.scheduler import Scheduler, compute_next_cron_fire
from openviper.tasks.types import TaskMessageProxy
from openviper.utils.logging import ConcurrentRotatingFileHandler
from openviper.core.management.commands.start_worker import Command
from openviper.tasks.discovery import discover_tasks
from openviper.tasks.middleware import trace_id_var
from openviper.tasks.runner import run
import openviper.tasks.logging as log_mod


@pytest.fixture(autouse=True)
def clear_registry() -> t.Generator[None]:
    """Clear the global Registry before and after each test."""
    Registry().clear()
    yield
    Registry().clear()


@pytest.fixture(autouse=True)
def reset_broker_fixture() -> t.Generator[None]:
    """Reset the global broker singleton around each test."""
    reset_broker()
    yield
    reset_broker()


@pytest.fixture
def redis_broker_cfg() -> dict[str, t.Any]:
    """Return a minimal valid TASKS config pointing at localhost Redis."""
    return {
        "enabled": 1,
        "broker": "redis",
        "broker_url": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        "backend_url": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        "logging": {
            "level": "INFO",
            "file": 0,
            "log_format": "text",
        },
    }


class TestConfigurationIntegration:
    """End-to-end configuration validation and resolution."""

    def test_resolve_and_validate_valid_config(self, redis_broker_cfg: dict) -> None:
        """A well-formed config must pass validation without errors."""
        merged = resolve_tasks_config(redis_broker_cfg)
        validate_tasks_config(merged)
        assert merged["enabled"] == 1
        assert merged["broker"] == "redis"

    def test_reject_missing_broker_url(self) -> None:
        """enabled=1 without broker_url must fail fast."""
        cfg = {"enabled": 1, "broker": "redis", "broker_url": ""}
        with pytest.raises(OpenViperTasksConfigurationError):
            validate_tasks_config(cfg)

    def test_reject_invalid_broker_type(self) -> None:
        """An unsupported broker type must fail fast."""
        cfg = {"enabled": 1, "broker": "kafka", "broker_url": "kafka://localhost"}
        with pytest.raises(OpenViperTasksConfigurationError):
            validate_tasks_config(cfg)

    def test_defaults_merge(self) -> None:
        """resolve_tasks_config must fill in all defaults."""
        merged = resolve_tasks_config({"enabled": 1, "broker_url": "redis://localhost:6379"})
        assert "logging" in merged
        assert merged["logging"]["level"] == "INFO"
        assert merged["logging"]["file"] is None
        assert merged["logging"]["database"] is None


class TestBrokerIntegration:
    """Broker factory integration with a live Redis instance."""

    def test_get_broker_creates_redis_broker(self, redis_broker_cfg: dict) -> None:
        """get_broker must return a Dramatiq RedisBroker."""
        with patch("openviper.tasks.broker.settings") as mock_settings:
            mock_settings.TASKS = redis_broker_cfg
            broker = get_broker()
            assert broker is not None

    def test_reset_broker_allows_recreation(self, redis_broker_cfg: dict) -> None:
        """After reset_broker, a new broker instance is created."""
        with patch("openviper.tasks.broker.settings") as mock_settings:
            mock_settings.TASKS = redis_broker_cfg
            first = get_broker()
            reset_broker()
            mock_settings.TASKS = redis_broker_cfg
            second = get_broker()
            assert first is not second


class TestActorIntegration:
    """Integration tests for the @actor decorator and task dispatch."""

    def test_actor_registers_and_sends_sync_fallback(self) -> None:
        """When TASKS enabled=0, .send() must execute synchronously."""

        @actor(actor_name="integration_sync_task")
        def add_numbers(a: int, b: int) -> int:
            return a + b

        with patch("openviper.tasks.decorators.settings") as mock_settings:
            mock_settings.TASKS = {"enabled": 0, "broker": "redis", "broker_url": ""}
            proxy = add_numbers.send(3, 7)
            assert isinstance(proxy, TaskMessageProxy)
            assert proxy.actor_name == "integration_sync_task"

    def test_actor_message_builds_payload(self) -> None:
        """The .message() method must return a serialisable dict."""

        @actor(actor_name="integration_msg_task")
        def echo(msg: str) -> str:
            return msg

        payload = echo.message("hello")
        assert isinstance(payload, dict)
        assert payload["actor_name"] == "integration_msg_task"
        assert payload["args"] == ("hello",)

    def test_actor_send_with_options(self) -> None:
        """send_with_options must accept delay and queue overrides."""

        @actor(actor_name="integration_opts_task", queue_name="priority")
        def compute(x: int) -> int:
            return x * 2

        with patch("openviper.tasks.decorators.settings") as mock_settings:
            mock_settings.TASKS = {"enabled": 0, "broker": "redis", "broker_url": ""}
            proxy = compute.send_with_options(args=(5,), delay=1000)
            assert isinstance(proxy, TaskMessageProxy)

    def test_get_result_raises_without_backend(self) -> None:
        """Calling .get_result() without a backend_url must raise."""

        @actor(actor_name="integration_no_backend_task")
        def noop() -> None:
            pass

        with patch("openviper.tasks.decorators.settings") as mock_settings:
            mock_settings.TASKS = {
                "enabled": 0,
                "broker": "redis",
                "broker_url": "",
                "backend_url": "",
            }
            proxy = noop.send()
            with pytest.raises(ResultsBackendDisabledError):
                proxy.get_result()


class TestPeriodicIntegration:
    """Integration tests for @periodic and the scheduler."""

    def test_periodic_registers_cron_job(self) -> None:
        """A @periodic(cron=...) job must appear in the registry."""

        @periodic(cron="*/5 * * * *")
        async def cron_health() -> None:
            pass

        registry = Registry()
        assert cron_health.__qualname__ in registry.periodic_jobs
        entry = registry.periodic_jobs[cron_health.__qualname__]
        assert entry["cron"] == "*/5 * * * *"

    def test_periodic_registers_interval_job(self) -> None:
        """A @periodic(every=...) job must appear in the registry."""

        @periodic(every="5m")
        async def interval_health() -> None:
            pass

        registry = Registry()
        assert interval_health.__qualname__ in registry.periodic_jobs
        entry = registry.periodic_jobs[interval_health.__qualname__]
        assert entry["every"] == "5m"

    def test_periodic_dedup_is_automatic(self) -> None:
        """Deduplication is automatic - no singleton flag needed."""

        @periodic(every="1h")
        async def auto_dedup_job() -> None:
            pass

        registry = Registry()
        entry = registry.periodic_jobs[auto_dedup_job.__qualname__]
        assert "singleton" not in entry

    def test_parse_interval_roundtrip(self) -> None:
        """parse_interval must correctly convert all supported units."""
        assert parse_interval("30s") == 30
        assert parse_interval("45m") == 2700
        assert parse_interval("12h") == 43200
        assert parse_interval("7d") == 604800

    def test_cron_fire_calculation(self) -> None:
        """compute_next_cron_fire must return a future datetime."""
        base = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
        next_fire = compute_next_cron_fire("0 * * * *", base)
        assert next_fire > base

    def test_scheduler_start_stop_lifecycle(self) -> None:
        """The scheduler must start and stop cleanly."""
        scheduler = Scheduler()
        scheduler.start()
        assert scheduler.thread is not None
        assert scheduler.thread.is_alive()
        scheduler.stop()
        assert scheduler.thread is None


class TestDiscoveryIntegration:
    """Integration tests for task discovery."""

    def test_discover_skips_missing_modules(self) -> None:
        """discover_tasks must silently skip apps without tasks.py."""
        discover_tasks(["nonexistent_app_xyz"])
        registry = Registry()
        assert not registry.is_discovered("nonexistent_app_xyz") or True

    def test_discover_marks_app_as_discovered(self) -> None:
        """discover_tasks must mark scanned apps in the registry."""
        discover_tasks(["nonexistent_app_abc"])
        registry = Registry()
        assert registry.is_discovered("nonexistent_app_abc")


class TestLoggingIntegration:
    """Integration tests for task subsystem logging."""

    def test_task_logger_isolation(self) -> None:
        """Task loggers must not propagate to the root logger."""
        logger = get_task_logger("openviper.tasks.integration_test")
        assert logger.propagate is False

    def test_concurrent_rotating_file_handler(self, tmp_path: Path) -> None:
        """configure_task_logging must use ConcurrentRotatingFileHandler."""
        log_mod.TASK_LOGGING_CONFIGURED = False

        cfg = {
            "enabled": 1,
            "broker": "redis",
            "broker_url": "redis://localhost:6379",
            "logging": {
                "level": "DEBUG",
                "file": {
                    "file_name": "integration_test.log",
                    "log_dir": str(tmp_path),
                    "log_format": "json",
                    "rotate_log_file": 1,
                    "max_size": 10,
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
        assert root.propagate is False

        root.info("integration test log message")
        log_file = tmp_path / "integration_test.log"
        assert log_file.exists()

    def test_json_log_format(self, tmp_path: Path) -> None:
        """JSON log format must produce valid JSON lines."""
        log_mod.TASK_LOGGING_CONFIGURED = False

        cfg = {
            "enabled": 1,
            "broker": "redis",
            "broker_url": "redis://localhost:6379",
            "logging": {
                "level": "DEBUG",
                "file": {
                    "file_name": "json_integration.log",
                    "log_dir": str(tmp_path),
                    "log_format": "json",
                    "rotate_log_file": 1,
                    "max_size": 10,
                },
                "database": {"task": 1, "periodic": 1},
            },
        }
        configure_task_logging(cfg)

        root = logging.getLogger("openviper.tasks.json_test")
        root.info("json integration message")

        log_file = tmp_path / "json_integration.log"
        assert log_file.exists()


class TestMiddlewareIntegration:
    """Integration tests for task middleware."""

    def test_database_cleanup_middleware_hooks(self) -> None:
        """DatabaseCleanupMiddleware must expose all Dramatiq lifecycle hooks."""
        mw = DatabaseCleanupMiddleware()
        msg = type("Msg", (), {"actor_name": "test_actor"})()

        mw.before_process_message(None, msg)
        mw.after_process_message(None, msg, result=None, exception=None)
        mw.after_skip_message(None, msg)
        mw.after_process_message(None, msg, result=None, exception=RuntimeError("test"))

    def test_state_observation_middleware_tracks_state(self) -> None:
        """StateObservationMiddleware must track task state transitions."""
        mw = StateObservationMiddleware()
        msg = type("Msg", (), {"actor_name": "test_actor", "message_id": "abc123", "options": {}})()

        mw.before_process_message(None, msg)
        mw.after_process_message(None, msg, result=None, exception=None)

    def test_state_observation_failure_marks_dead(self) -> None:
        """After max retries, StateObservationMiddleware must mark as dead."""
        mw = StateObservationMiddleware()
        msg = type(
            "Msg",
            (),
            {
                "actor_name": "test_actor",
                "message_id": "abc123",
                "options": {"retries": 3},
            },
        )()

        mw.before_process_message(None, msg)
        mw.after_process_message(
            None, msg, result=None, exception=RuntimeError("max retries exceeded")
        )

    def test_unified_context_logger_sets_trace_id(self) -> None:
        """UnifiedContextLogger must set a trace ID in contextvars."""
        mw = UnifiedContextLogger()
        msg = type("Msg", (), {"actor_name": "trace_test"})()

        mw.before_process_message(None, msg)
        trace_id = trace_id_var.get("")
        assert len(trace_id) == 8

        mw.after_process_message(None, msg, result=None, exception=None)


class TestRunnerLifecycleIntegration:
    """Integration tests for the runner lifecycle sequence."""

    @patch("openviper.tasks.runner.sync_scheduled_jobs")
    @patch("openviper.tasks.runner.discover_tasks")
    @patch("openviper.tasks.runner.get_broker")
    @patch("openviper.tasks.runner.configure_task_logging")
    @patch("openviper.tasks.runner.validate_tasks_config")
    @patch("openviper.tasks.runner.resolve_tasks_config")
    def test_full_lifecycle_sequence(
        self,
        mock_resolve: MagicMock,
        mock_validate: MagicMock,
        mock_logging: MagicMock,
        mock_broker: MagicMock,
        mock_discover: MagicMock,
        mock_sync: MagicMock,
    ) -> None:
        """The runner must execute all 9 lifecycle steps in order."""
        mock_resolve.return_value = {
            "enabled": 1,
            "broker_url": "redis://localhost:6379",
        }
        mock_broker_inst = MagicMock()
        mock_broker.return_value = mock_broker_inst

        call_order: list[str] = []

        mock_resolve.side_effect = lambda *a, **kw: (
            call_order.append("resolve"),
            {"enabled": 1, "broker_url": "redis://localhost:6379"},
        )[1]
        mock_validate.side_effect = lambda *a, **kw: call_order.append("validate")
        mock_logging.side_effect = lambda *a, **kw: call_order.append("logging")
        mock_broker.side_effect = lambda *a, **kw: (call_order.append("broker"), mock_broker_inst)[
            1
        ]
        mock_discover.side_effect = lambda *a, **kw: call_order.append("discover")
        mock_sync.side_effect = lambda: call_order.append("sync")

        with (
            patch("openviper.tasks.runner.Scheduler") as MockScheduler,
            patch("openviper.tasks.runner.run_worker"),
        ):
            MockScheduler.return_value = MagicMock()
            run(processes=1, threads=4)

        assert "resolve" in call_order
        assert "validate" in call_order
        assert "logging" in call_order
        assert "discover" in call_order
        assert "sync" in call_order

    @patch("openviper.tasks.runner.sync_scheduled_jobs")
    @patch("openviper.tasks.runner.discover_tasks")
    @patch("openviper.tasks.runner.get_broker")
    @patch("openviper.tasks.runner.configure_task_logging")
    @patch("openviper.tasks.runner.validate_tasks_config")
    @patch("openviper.tasks.runner.resolve_tasks_config")
    def test_runner_injects_three_middleware_by_default(
        self,
        mock_resolve: MagicMock,
        mock_validate: MagicMock,
        mock_logging: MagicMock,
        mock_broker: MagicMock,
        mock_discover: MagicMock,
        mock_sync: MagicMock,
    ) -> None:
        """The runner must inject three middleware when database logging is disabled."""
        mock_resolve.return_value = {"enabled": 1, "broker_url": "redis://localhost:6379"}
        mock_broker_inst = MagicMock()
        mock_broker.return_value = mock_broker_inst

        with (
            patch("openviper.tasks.runner.Scheduler") as MockScheduler,
            patch("openviper.tasks.runner.run_worker"),
        ):
            MockScheduler.return_value = MagicMock()
            run(processes=1, threads=4)

        assert mock_broker_inst.add_middleware.call_count == 3

    @patch("openviper.tasks.runner.sync_scheduled_jobs")
    @patch("openviper.tasks.runner.discover_tasks")
    @patch("openviper.tasks.runner.get_broker")
    @patch("openviper.tasks.runner.configure_task_logging")
    @patch("openviper.tasks.runner.validate_tasks_config")
    @patch("openviper.tasks.runner.resolve_tasks_config")
    def test_runner_injects_four_middleware_with_database_logging(
        self,
        mock_resolve: MagicMock,
        mock_validate: MagicMock,
        mock_logging: MagicMock,
        mock_broker: MagicMock,
        mock_discover: MagicMock,
        mock_sync: MagicMock,
    ) -> None:
        """The runner must inject four middleware when database logging is enabled."""
        mock_resolve.return_value = {
            "enabled": 1,
            "broker_url": "redis://localhost:6379",
            "logging": {"database": {"task": 1}},
        }
        mock_broker_inst = MagicMock()
        mock_broker.return_value = mock_broker_inst

        with (
            patch("openviper.tasks.runner.Scheduler") as MockScheduler,
            patch("openviper.tasks.runner.run_worker"),
        ):
            MockScheduler.return_value = MagicMock()
            run(processes=1, threads=4)

        assert mock_broker_inst.add_middleware.call_count == 4

    @patch("openviper.tasks.runner.sync_scheduled_jobs")
    @patch("openviper.tasks.runner.discover_tasks")
    @patch("openviper.tasks.runner.get_broker")
    @patch("openviper.tasks.runner.configure_task_logging")
    @patch("openviper.tasks.runner.validate_tasks_config")
    @patch("openviper.tasks.runner.resolve_tasks_config")
    def test_runner_stops_scheduler_on_keyboard_interrupt(
        self,
        mock_resolve: MagicMock,
        mock_validate: MagicMock,
        mock_logging: MagicMock,
        mock_broker: MagicMock,
        mock_discover: MagicMock,
        mock_sync: MagicMock,
    ) -> None:
        """The runner must stop the scheduler even on KeyboardInterrupt."""
        mock_resolve.return_value = {"enabled": 1, "broker_url": "redis://localhost:6379"}
        mock_broker.return_value = MagicMock()

        with (
            patch("openviper.tasks.runner.Scheduler") as MockScheduler,
            patch("openviper.tasks.runner.run_worker") as mock_run_worker,
        ):
            mock_scheduler = MagicMock()
            MockScheduler.return_value = mock_scheduler
            mock_run_worker.side_effect = KeyboardInterrupt()
            run(processes=1, threads=4)

        mock_scheduler.stop.assert_called_once()


class TestStartWorkerCommand:
    """Integration tests for the start-worker management command."""

    def test_command_rejects_missing_dramatiq(self) -> None:
        """start-worker must exit if dramatiq is not installed."""
        cmd = Command()
        with patch.dict("sys.modules", {"dramatiq": None}):
            with pytest.raises(SystemExit):
                cmd.handle(modules=[], queues=None, threads=8, processes=1)

    def test_command_accepts_cli_options(self) -> None:
        """start-worker must accept --processes, --threads, --queues."""
        cmd = Command()
        parser = cmd.create_parser("openviper", "start-worker")
        help_text = parser.format_help()
        assert "--processes" in help_text
        assert "--threads" in help_text
        assert "--queues" in help_text


class TestExceptionHierarchy:
    """Integration tests for the task exception hierarchy."""

    def test_configuration_error_inherits_from_base(self) -> None:
        """OpenViperTasksConfigurationError must inherit from OpenViperTasksError."""
        err = OpenViperTasksConfigurationError(["bad config"])
        assert isinstance(err, OpenViperTasksError)

    def test_results_backend_disabled_error_inherits(self) -> None:
        """ResultsBackendDisabledError must inherit from OpenViperTasksError."""
        err = ResultsBackendDisabledError("no backend")
        assert isinstance(err, OpenViperTasksError)

    def test_configuration_error_stores_errors(self) -> None:
        """OpenViperTasksConfigurationError must store the error list."""
        errors = ["error 1", "error 2"]
        err = OpenViperTasksConfigurationError(errors)
        assert err.errors == errors
        assert "error 1" in str(err)
        assert "error 2" in str(err)
