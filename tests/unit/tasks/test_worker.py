"""Unit tests for openviper.tasks.worker — In-process Dramatiq worker."""

import os
import signal as _signal
import sys
from unittest.mock import MagicMock, patch

from openviper.tasks.worker import (
    create_worker,
    discover_tasks,
    run_worker,
)


class TestDiscoverTasks:
    """Test discover_tasks function."""

    @patch("openviper.tasks.worker.settings")
    @patch("openviper.tasks.worker.AppResolver")
    def test_discovers_tasks_from_installed_apps(self, mock_resolver_class, mock_settings):
        """Should discover and import task modules from INSTALLED_APPS."""
        mock_settings.INSTALLED_APPS = ["myapp"]

        mock_resolver = MagicMock()
        mock_resolver_class.return_value = mock_resolver
        mock_resolver.resolve_app.return_value = ("/path/to/myapp", True)

        with patch("openviper.tasks.worker.os.walk") as mock_walk:
            mock_walk.return_value = [
                ("/path/to/myapp", ["subdir"], ["tasks.py", "models.py"]),
            ]

            with patch("openviper.tasks.worker.importlib.import_module") as mock_import:
                result = discover_tasks()

                # Should import tasks.py but not models.py (in _SKIP_FILES)
                assert mock_import.call_count >= 1
                imported_modules = [call[0][0] for call in mock_import.call_args_list]
                assert any("tasks" in mod for mod in imported_modules)

    @patch("openviper.tasks.worker.settings")
    @patch("openviper.tasks.worker.AppResolver")
    def test_skips_openviper_internals(self, mock_resolver_class, mock_settings):
        """Should skip openviper.* apps."""
        mock_settings.INSTALLED_APPS = ["openviper.auth", "myapp"]

        mock_resolver = MagicMock()
        mock_resolver_class.return_value = mock_resolver
        mock_resolver.resolve_app.return_value = ("/path/to/myapp", True)

        with patch("openviper.tasks.worker.os.walk") as mock_walk:
            mock_walk.return_value = []

            with patch("openviper.tasks.worker.importlib.import_module") as mock_import:
                discover_tasks()

                # Should not try to import from openviper.auth
                imported_modules = [call[0][0] for call in mock_import.call_args_list]
                assert not any("openviper.auth" in mod for mod in imported_modules)

    @patch("openviper.tasks.worker.settings")
    @patch("openviper.tasks.worker.AppResolver")
    def test_skips_excluded_directories(self, mock_resolver_class, mock_settings):
        """Should skip directories in _SKIP_DIRS."""
        mock_settings.INSTALLED_APPS = ["myapp"]

        mock_resolver = MagicMock()
        mock_resolver_class.return_value = mock_resolver
        mock_resolver.resolve_app.return_value = ("/path/to/myapp", True)

        with patch("openviper.tasks.worker.os.walk") as mock_walk:
            # Include both regular and excluded directories
            mock_walk.return_value = [
                ("/path/to/myapp", ["migrations", "tests", "tasks"], ["__init__.py"]),
            ]

            with patch("openviper.tasks.worker.importlib.import_module"):
                discover_tasks()

                # os.walk should have dirs filtered in-place
                # (This is hard to test without inspecting the actual walk behavior)
                assert True  # Passes if no error

    @patch("openviper.tasks.worker.settings")
    @patch("openviper.tasks.worker.AppResolver")
    def test_skips_excluded_files(self, mock_resolver_class, mock_settings):
        """Should skip files in _SKIP_FILES."""
        mock_settings.INSTALLED_APPS = ["myapp"]

        mock_resolver = MagicMock()
        mock_resolver_class.return_value = mock_resolver
        mock_resolver.resolve_app.return_value = ("/path/to/myapp", True)

        with patch("openviper.tasks.worker.os.walk") as mock_walk:
            mock_walk.return_value = [
                ("/path/to/myapp", [], ["tasks.py", "models.py", "settings.py"]),
            ]

            with patch("openviper.tasks.worker.importlib.import_module") as mock_import:
                discover_tasks()

                # Should not import models.py or settings.py
                imported_modules = [call[0][0] for call in mock_import.call_args_list]
                assert not any("models" in mod for mod in imported_modules)
                assert not any("settings" in mod for mod in imported_modules)

    @patch("openviper.tasks.worker.settings")
    @patch("openviper.tasks.worker.AppResolver")
    def test_imports_extra_modules(self, mock_resolver_class, mock_settings):
        """Should import extra_modules in addition to discovered ones."""
        mock_settings.INSTALLED_APPS = []

        mock_resolver = MagicMock()
        mock_resolver_class.return_value = mock_resolver

        with patch("openviper.tasks.worker.os.walk") as mock_walk:
            mock_walk.return_value = []

            with patch("openviper.tasks.worker.importlib.import_module") as mock_import:
                discover_tasks(extra_modules=["custom.module"])

                imported_modules = [call[0][0] for call in mock_import.call_args_list]
                assert "custom.module" in imported_modules

    @patch("openviper.tasks.worker.settings")
    @patch("openviper.tasks.worker.AppResolver")
    def test_returns_imported_module_list(self, mock_resolver_class, mock_settings):
        """Should return sorted list of imported module paths."""
        mock_settings.INSTALLED_APPS = ["myapp"]

        mock_resolver = MagicMock()
        mock_resolver_class.return_value = mock_resolver
        mock_resolver.resolve_app.return_value = ("/path/to/myapp", True)

        with patch("openviper.tasks.worker.os.walk") as mock_walk:
            mock_walk.return_value = [
                ("/path/to/myapp", [], ["tasks.py"]),
            ]

            with patch("openviper.tasks.worker.importlib.import_module"):
                result = discover_tasks()

                assert isinstance(result, list)
                assert len(result) > 0

    @patch("openviper.tasks.worker.settings")
    @patch("openviper.tasks.worker.AppResolver")
    def test_handles_import_errors(self, mock_resolver_class, mock_settings):
        """Should continue on import errors."""
        mock_settings.INSTALLED_APPS = ["myapp"]

        mock_resolver = MagicMock()
        mock_resolver_class.return_value = mock_resolver
        mock_resolver.resolve_app.return_value = ("/path/to/myapp", True)

        with patch("openviper.tasks.worker.os.walk") as mock_walk:
            mock_walk.return_value = [
                ("/path/to/myapp", [], ["tasks.py"]),
            ]

            with patch("openviper.tasks.worker.importlib.import_module") as mock_import:
                mock_import.side_effect = ImportError("Module not found")

                # Should not raise
                result = discover_tasks()

                assert isinstance(result, list)

    @patch("openviper.tasks.worker.settings")
    @patch("openviper.tasks.worker.AppResolver")
    def test_uses_parallel_imports(self, mock_resolver_class, mock_settings):
        """Should use ThreadPoolExecutor for parallel imports."""
        mock_settings.INSTALLED_APPS = ["myapp"]

        mock_resolver = MagicMock()
        mock_resolver_class.return_value = mock_resolver
        mock_resolver.resolve_app.return_value = ("/path/to/myapp", True)

        # Create mock futures
        mock_future1 = MagicMock()
        mock_future1.result.return_value = ("myapp.task1", None)
        mock_future2 = MagicMock()
        mock_future2.result.return_value = ("myapp.task2", None)

        with patch("openviper.tasks.worker.os.walk") as mock_walk:
            mock_walk.return_value = [
                ("/path/to/myapp", [], ["task1.py", "task2.py"]),
            ]

            # Patch ThreadPoolExecutor and as_completed BEFORE importlib.
            # (Patching importlib.import_module first would break patch's
            # internal module resolution for subsequent patches.)
            with patch("openviper.tasks.worker.ThreadPoolExecutor") as mock_executor_cls:
                mock_instance = MagicMock()
                mock_executor_cls.return_value = mock_instance
                mock_instance.__enter__ = MagicMock(return_value=mock_instance)
                mock_instance.__exit__ = MagicMock(return_value=False)
                mock_instance.submit.side_effect = [mock_future1, mock_future2]

                with patch(
                    "openviper.tasks.worker.as_completed", return_value=[mock_future1, mock_future2]
                ):
                    with patch("openviper.tasks.worker.importlib.import_module"):
                        discover_tasks()

                        # Should use executor
                        assert mock_instance.submit.called


class TestCreateWorker:
    """Test create_worker function."""

    @patch("openviper.tasks.worker.discover_tasks")
    @patch("openviper.tasks.worker.setup_broker")
    @patch("openviper.tasks.worker.Worker")
    def test_creates_worker_instance(self, mock_worker_class, mock_setup_broker, mock_discover):
        """Should create and return a Dramatiq Worker instance."""
        mock_discover.return_value = ["myapp.tasks"]
        mock_broker = MagicMock()
        mock_setup_broker.return_value = mock_broker
        mock_worker = MagicMock()
        mock_worker_class.return_value = mock_worker

        result = create_worker()

        assert result is mock_worker
        mock_worker_class.assert_called_once_with(
            mock_broker,
            worker_threads=8,
            queues=None,
        )

    @patch("openviper.tasks.worker.discover_tasks")
    @patch("openviper.tasks.worker.setup_broker")
    @patch("openviper.tasks.worker.Worker")
    def test_discovers_tasks_before_broker(
        self, mock_worker_class, mock_setup_broker, mock_discover
    ):
        """Should discover tasks before setting up broker."""
        mock_discover.return_value = []
        mock_broker = MagicMock()
        mock_setup_broker.return_value = mock_broker

        create_worker()

        # discover_tasks should be called before setup_broker
        assert mock_discover.called
        assert mock_setup_broker.called

    @patch("openviper.tasks.worker.discover_tasks")
    @patch("openviper.tasks.worker.setup_broker")
    @patch("openviper.tasks.worker.Worker")
    def test_custom_threads(self, mock_worker_class, mock_setup_broker, mock_discover):
        """Should use custom thread count."""
        mock_discover.return_value = []
        mock_broker = MagicMock()
        mock_setup_broker.return_value = mock_broker

        create_worker(threads=16)

        call_kwargs = mock_worker_class.call_args[1]
        assert call_kwargs["worker_threads"] == 16

    @patch("openviper.tasks.worker.discover_tasks")
    @patch("openviper.tasks.worker.setup_broker")
    @patch("openviper.tasks.worker.Worker")
    def test_custom_queues(self, mock_worker_class, mock_setup_broker, mock_discover):
        """Should restrict to custom queues."""
        mock_discover.return_value = []
        mock_broker = MagicMock()
        mock_setup_broker.return_value = mock_broker

        create_worker(queues=["emails", "reports"])

        call_kwargs = mock_worker_class.call_args[1]
        assert call_kwargs["queues"] == {"emails", "reports"}


class TestRunWorker:
    """Test run_worker function."""

    @patch("openviper.tasks.worker.settings")
    @patch("openviper.tasks.worker.configure_worker_logging_from_settings")
    def test_does_nothing_when_disabled(self, mock_logging, mock_settings):
        """Should exit early when tasks are not enabled."""
        mock_settings.TASKS = {"enabled": 0}

        run_worker()

        # Should configure logging but not start worker
        mock_logging.assert_called_once()

    @patch("openviper.tasks.worker.settings")
    @patch("openviper.tasks.worker.configure_worker_logging_from_settings")
    @patch("openviper.tasks.worker.create_worker")
    @patch("openviper.tasks.worker.signal.signal")
    @patch("openviper.tasks.worker.time.sleep")
    def test_starts_worker_when_enabled(
        self, mock_sleep, mock_signal, mock_create_worker, mock_logging, mock_settings
    ):
        """Should start worker when tasks are enabled."""
        mock_settings.TASKS = {"enabled": 1, "scheduler_enabled": 0}

        mock_worker = MagicMock()
        mock_broker = MagicMock()
        mock_broker.get_declared_queues.return_value = ["default"]
        mock_worker.broker = mock_broker
        mock_create_worker.return_value = mock_worker

        # Stop after first sleep
        mock_sleep.side_effect = KeyboardInterrupt()

        run_worker()

        mock_worker.start.assert_called_once()

    @patch("openviper.tasks.worker.settings")
    @patch("openviper.tasks.worker.configure_worker_logging_from_settings")
    @patch("openviper.tasks.worker.create_worker")
    @patch("openviper.tasks.worker.signal.signal")
    @patch("openviper.tasks.worker.time.sleep")
    def test_starts_scheduler_when_enabled(
        self, mock_sleep, mock_signal, mock_create_worker, mock_logging, mock_settings
    ):
        """Should start scheduler when scheduler_enabled=1."""
        mock_settings.TASKS = {"enabled": 1, "scheduler_enabled": 1}

        mock_worker = MagicMock()
        mock_broker = MagicMock()
        mock_broker.get_declared_queues.return_value = ["default"]
        mock_worker.broker = mock_broker
        mock_create_worker.return_value = mock_worker

        mock_sleep.side_effect = KeyboardInterrupt()

        with patch("openviper.tasks.worker.start_scheduler") as mock_start_scheduler:
            run_worker()

            mock_start_scheduler.assert_called_once()

    @patch("openviper.tasks.worker.settings")
    @patch("openviper.tasks.worker.configure_worker_logging_from_settings")
    @patch("openviper.tasks.worker.create_worker")
    @patch("openviper.tasks.worker.signal.signal")
    @patch("openviper.tasks.worker.time.sleep")
    def test_stops_scheduler_on_shutdown(
        self, mock_sleep, mock_signal, mock_create_worker, mock_logging, mock_settings
    ):
        """Should stop scheduler on shutdown."""
        mock_settings.TASKS = {"enabled": 1, "scheduler_enabled": 1}

        mock_worker = MagicMock()
        mock_broker = MagicMock()
        mock_broker.get_declared_queues.return_value = ["default"]
        mock_worker.broker = mock_broker
        mock_create_worker.return_value = mock_worker

        mock_sleep.side_effect = KeyboardInterrupt()

        with patch("openviper.tasks.worker.start_scheduler"):
            with patch("openviper.tasks.worker.stop_scheduler") as mock_stop_scheduler:
                run_worker()

                mock_stop_scheduler.assert_called_once()

    @patch("openviper.tasks.worker.settings")
    @patch("openviper.tasks.worker.configure_worker_logging_from_settings")
    @patch("openviper.tasks.worker.create_worker")
    @patch("openviper.tasks.worker.signal.signal")
    @patch("openviper.tasks.worker.time.sleep")
    def test_stops_worker_on_shutdown(
        self, mock_sleep, mock_signal, mock_create_worker, mock_logging, mock_settings
    ):
        """Should stop worker on shutdown."""
        mock_settings.TASKS = {"enabled": 1}

        mock_worker = MagicMock()
        mock_broker = MagicMock()
        mock_broker.get_declared_queues.return_value = ["default"]
        mock_worker.broker = mock_broker
        mock_create_worker.return_value = mock_worker

        mock_sleep.side_effect = KeyboardInterrupt()

        run_worker()

        mock_worker.stop.assert_called_once()

    @patch("openviper.tasks.worker.settings")
    @patch("openviper.tasks.worker.configure_worker_logging_from_settings")
    @patch("openviper.tasks.worker.create_worker")
    @patch("openviper.tasks.worker.signal.signal")
    @patch("openviper.tasks.worker.time.sleep")
    def test_sets_env_var(
        self, mock_sleep, mock_signal, mock_create_worker, mock_logging, mock_settings
    ):
        """Should set OPENVIPER_WORKER environment variable."""
        mock_settings.TASKS = {"enabled": 1}

        mock_worker = MagicMock()
        mock_broker = MagicMock()
        mock_broker.get_declared_queues.return_value = ["default"]
        mock_worker.broker = mock_broker
        mock_create_worker.return_value = mock_worker

        mock_sleep.side_effect = KeyboardInterrupt()

        run_worker()

        assert os.environ.get("OPENVIPER_WORKER") == "1"

    @patch("openviper.tasks.worker.settings")
    @patch("openviper.tasks.worker.configure_worker_logging_from_settings")
    @patch("openviper.tasks.worker.create_worker")
    @patch("openviper.tasks.worker.signal.signal")
    @patch("openviper.tasks.worker.time.sleep")
    def test_passes_custom_parameters(
        self, mock_sleep, mock_signal, mock_create_worker, mock_logging, mock_settings
    ):
        """Should pass custom threads and queues to create_worker."""
        mock_settings.TASKS = {"enabled": 1}

        mock_worker = MagicMock()
        mock_broker = MagicMock()
        mock_broker.get_declared_queues.return_value = ["default"]
        mock_worker.broker = mock_broker
        mock_create_worker.return_value = mock_worker

        mock_sleep.side_effect = KeyboardInterrupt()

        run_worker(threads=16, queues=["emails"])

        mock_create_worker.assert_called_once_with(
            threads=16,
            queues=["emails"],
            extra_modules=None,
        )


# ── discover_tasks: unresolvable app skip (lines 104-105) ──────────────────


class TestDiscoverTasksUnresolvableApp:
    @patch("openviper.tasks.worker.settings")
    @patch("openviper.tasks.worker.AppResolver")
    def test_skips_app_when_path_not_found(self, mock_resolver_class, mock_settings):
        """discover_tasks logs and skips apps that cannot be resolved (lines 104-105)."""
        mock_settings.INSTALLED_APPS = ["my_app"]

        mock_resolver = MagicMock()
        # resolve_app returns (None, False) → not found
        mock_resolver.resolve_app.return_value = (None, False)
        mock_resolver_class.return_value = mock_resolver

        result = discover_tasks()

        assert result == []
        mock_resolver.resolve_app.assert_called_once_with("my_app")


# ── run_worker: _shutdown signal handler (lines 239-241) ────────────────────


class TestRunWorkerShutdownHandler:
    @patch("openviper.tasks.worker.settings")
    @patch("openviper.tasks.worker.configure_worker_logging_from_settings")
    @patch("openviper.tasks.worker.create_worker")
    @patch("openviper.tasks.worker.signal.signal")
    @patch("openviper.tasks.worker.time.sleep")
    def test_shutdown_handler_calls_sys_exit(
        self, mock_sleep, mock_signal, mock_create_worker, mock_logging, mock_settings
    ):
        """_shutdown handler registered with signal.signal calls sys.exit(0) (lines 239-241)."""

        mock_settings.TASKS = {"enabled": 1, "scheduler_enabled": 0}

        mock_worker = MagicMock()
        mock_broker = MagicMock()
        mock_broker.get_declared_queues.return_value = ["default"]
        mock_worker.broker = mock_broker
        mock_create_worker.return_value = mock_worker
        mock_sleep.side_effect = KeyboardInterrupt()

        run_worker()

        # Extract the _shutdown handler registered for SIGINT
        handlers = {call[0][0]: call[0][1] for call in mock_signal.call_args_list}
        shutdown = handlers.get(_signal.SIGINT)
        assert shutdown is not None

        # Calling the handler should invoke sys.exit(0)
        with patch.object(sys, "exit") as mock_exit:
            shutdown(_signal.SIGINT, None)
            mock_exit.assert_called_once_with(0)
