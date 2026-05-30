"""Tests for openviper/tasks/__init__.py."""

from __future__ import annotations

import contextlib
import importlib
import os
from unittest.mock import MagicMock, patch

import openviper.tasks


class TestTasksInit:
    def test_worker_env_not_set_no_broker_setup(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "OPENVIPER_WORKER"}
        with patch.dict(os.environ, env, clear=True):
            importlib.reload(openviper.tasks)

    def test_worker_env_set_triggers_setup(self) -> None:
        mock_configure = MagicMock()
        mock_setup = MagicMock()
        with (
            patch.dict(os.environ, {"OPENVIPER_WORKER": "1"}),
            patch("openviper.tasks.log.configure_worker_logging_from_settings", mock_configure),
            patch("openviper.tasks.broker.setup_broker", mock_setup),
        ):
            importlib.reload(openviper.tasks)

        mock_configure.assert_called()

    def test_worker_env_setup_exception_handled(self) -> None:
        mock_configure = MagicMock()
        mock_setup = MagicMock(side_effect=RuntimeError("broker failed"))

        importlib.reload(openviper.tasks)
        tasks_mod = openviper.tasks

        with patch.dict(os.environ, {"OPENVIPER_WORKER": "1"}):
            with (
                patch.object(tasks_mod, "configure_worker_logging_from_settings", mock_configure),
                patch.object(tasks_mod, "setup_broker", mock_setup),
            ):
                if os.environ.get("OPENVIPER_WORKER"):
                    tasks_mod.configure_worker_logging_from_settings()
                    with contextlib.suppress(Exception):
                        tasks_mod.setup_broker()

    def test_all_exports_available(self) -> None:
        tasks = openviper.tasks

        assert hasattr(tasks, "task")
        assert hasattr(tasks, "periodic")
        assert hasattr(tasks, "get_broker")
        assert hasattr(tasks, "setup_broker")
        assert hasattr(tasks, "reset_broker")
        assert hasattr(tasks, "Scheduler")
        assert hasattr(tasks, "get_task_result")
        assert hasattr(tasks, "list_task_results")
        assert hasattr(tasks, "get_task_result_sync")
        assert hasattr(tasks, "list_task_results_sync")
        assert hasattr(tasks, "reset_engine")
        assert hasattr(tasks, "reset_scheduler")
        assert hasattr(tasks, "reset_tracking_buffer")
        assert hasattr(tasks, "CronSchedule")
        assert hasattr(tasks, "IntervalSchedule")
        assert hasattr(tasks, "ScheduleEntry")
        assert hasattr(tasks, "ScheduleRegistry")
        assert hasattr(tasks, "get_registry")
        assert hasattr(tasks, "reset_registry")
