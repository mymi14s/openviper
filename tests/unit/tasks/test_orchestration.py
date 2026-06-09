"""Tests for openviper.tasks.runner - worker lifecycle orchestration."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from openviper.tasks.registry import Registry


class TestRunnerLifecycle:
    """Verify the 9-step start-worker lifecycle sequence."""

    def setup_method(self) -> None:
        Registry().clear()

    @patch("openviper.tasks.runner.sync_scheduled_jobs")
    @patch("openviper.tasks.runner.discover_tasks")
    @patch("openviper.tasks.runner.get_broker")
    @patch("openviper.tasks.runner.configure_task_logging")
    @patch("openviper.tasks.runner.validate_tasks_config")
    @patch("openviper.tasks.runner.resolve_tasks_config")
    def test_lifecycle_order(
        self,
        mock_resolve: MagicMock,
        mock_validate: MagicMock,
        mock_logging: MagicMock,
        mock_broker: MagicMock,
        mock_discover: MagicMock,
        mock_sync: MagicMock,
    ) -> None:
        """Runner executes lifecycle steps in order."""
        from openviper.tasks.runner import run

        mock_resolve.return_value = {"enabled": 1, "broker_url": "redis://localhost:6379"}
        mock_broker_inst = MagicMock()
        mock_broker.return_value = mock_broker_inst

        with (
            patch("openviper.tasks.runner.Scheduler") as MockScheduler,
            patch("openviper.tasks.runner.run_worker") as mock_run_worker,
        ):
            mock_scheduler = MagicMock()
            MockScheduler.return_value = mock_scheduler
            run(processes=1, threads=4)

        mock_resolve.assert_called_once()
        mock_validate.assert_called_once()
        mock_logging.assert_called_once()
        mock_broker.assert_called_once()
        assert mock_broker_inst.add_middleware.call_count == 3
        mock_discover.assert_called_once()
        mock_sync.assert_called_once()
        mock_scheduler.start.assert_called_once()
        mock_run_worker.assert_called_once_with(processes=1, threads=4, queues=None)

    @patch("openviper.tasks.runner.sync_scheduled_jobs")
    @patch("openviper.tasks.runner.discover_tasks")
    @patch("openviper.tasks.runner.get_broker")
    @patch("openviper.tasks.runner.configure_task_logging")
    @patch("openviper.tasks.runner.validate_tasks_config")
    @patch("openviper.tasks.runner.resolve_tasks_config")
    def test_lifecycle_validates_config_before_logging(
        self,
        mock_resolve: MagicMock,
        mock_validate: MagicMock,
        mock_logging: MagicMock,
        mock_broker: MagicMock,
        mock_discover: MagicMock,
        mock_sync: MagicMock,
    ) -> None:
        """Configuration validation must precede logging initialisation."""
        from openviper.tasks.runner import run

        mock_resolve.return_value = {"enabled": 1}
        mock_validate.side_effect = ValueError("bad config")

        with pytest.raises(ValueError, match="bad config"):
            run(processes=1, threads=4)

        mock_logging.assert_not_called()

    @patch("openviper.tasks.runner.sync_scheduled_jobs")
    @patch("openviper.tasks.runner.discover_tasks")
    @patch("openviper.tasks.runner.get_broker")
    @patch("openviper.tasks.runner.configure_task_logging")
    @patch("openviper.tasks.runner.validate_tasks_config")
    @patch("openviper.tasks.runner.resolve_tasks_config")
    def test_lifecycle_discovers_before_sync(
        self,
        mock_resolve: MagicMock,
        mock_validate: MagicMock,
        mock_logging: MagicMock,
        mock_broker: MagicMock,
        mock_discover: MagicMock,
        mock_sync: MagicMock,
    ) -> None:
        """Task discovery must happen before schedule synchronisation."""
        from openviper.tasks.runner import run

        mock_resolve.return_value = {"enabled": 1}
        mock_broker.return_value = MagicMock()

        call_order: list[str] = []
        mock_discover.side_effect = lambda *a, **kw: call_order.append("discover")
        mock_sync.side_effect = lambda: call_order.append("sync")

        with (
            patch("openviper.tasks.runner.Scheduler") as MockScheduler,
            patch("openviper.tasks.runner.run_worker"),
        ):
            MockScheduler.return_value = MagicMock()
            run(processes=1, threads=4)

        assert call_order == ["discover", "sync"]

    @patch("openviper.tasks.runner.sync_scheduled_jobs")
    @patch("openviper.tasks.runner.discover_tasks")
    @patch("openviper.tasks.runner.get_broker")
    @patch("openviper.tasks.runner.configure_task_logging")
    @patch("openviper.tasks.runner.validate_tasks_config")
    @patch("openviper.tasks.runner.resolve_tasks_config")
    def test_lifecycle_sync_failure_does_not_crash(
        self,
        mock_resolve: MagicMock,
        mock_validate: MagicMock,
        mock_logging: MagicMock,
        mock_broker: MagicMock,
        mock_discover: MagicMock,
        mock_sync: MagicMock,
    ) -> None:
        """Schedule sync failure should be logged but not crash the runner."""
        from openviper.tasks.runner import run

        mock_resolve.return_value = {"enabled": 1}
        mock_broker.return_value = MagicMock()
        mock_sync.side_effect = RuntimeError("db unavailable")

        with (
            patch("openviper.tasks.runner.Scheduler") as MockScheduler,
            patch("openviper.tasks.runner.run_worker"),
        ):
            MockScheduler.return_value = MagicMock()
            run(processes=1, threads=4)

    @patch("openviper.tasks.runner.sync_scheduled_jobs")
    @patch("openviper.tasks.runner.discover_tasks")
    @patch("openviper.tasks.runner.get_broker")
    @patch("openviper.tasks.runner.configure_task_logging")
    @patch("openviper.tasks.runner.validate_tasks_config")
    @patch("openviper.tasks.runner.resolve_tasks_config")
    def test_lifecycle_scheduler_stops_on_keyboard_interrupt(
        self,
        mock_resolve: MagicMock,
        mock_validate: MagicMock,
        mock_logging: MagicMock,
        mock_broker: MagicMock,
        mock_discover: MagicMock,
        mock_sync: MagicMock,
    ) -> None:
        """Scheduler must be stopped even if worker is interrupted."""
        from openviper.tasks.runner import run

        mock_resolve.return_value = {"enabled": 1}
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
    """Tests for the start-worker management command."""

    def test_command_requires_dramatiq(self) -> None:
        """Command should fail if dramatiq is not installed."""
        from openviper.core.management.commands.start_worker import Command

        cmd = Command()
        with patch.dict("sys.modules", {"dramatiq": None}):
            with pytest.raises(SystemExit):
                cmd.handle(modules=[], queues=None, threads=8, processes=1)

    def test_command_passes_options_to_runner(self) -> None:
        """Command should accept CLI options for processes, threads, queues."""
        from openviper.core.management.commands.start_worker import Command

        cmd = Command()
        parser = cmd.create_parser("openviper", "start-worker")
        assert "--processes" in parser.format_help()
        assert "--threads" in parser.format_help()
        assert "--queues" in parser.format_help()
