import signal as signal_module
from unittest.mock import MagicMock, patch

from openviper.tasks.worker import discover_tasks, run_worker


def test_discover_tasks():
    # We patch inside the module namespace where they are used.
    # Note: discover_tasks uses 'resolver = AppResolver()'
    # So patching 'openviper.tasks.worker.AppResolver' is correct.

    with patch("openviper.tasks.worker.settings") as mock_settings:
        mock_settings.INSTALLED_APPS = ["myapp"]

        with patch("openviper.tasks.worker.AppResolver") as mock_resolver_cls:
            resolver_instance = MagicMock()
            mock_resolver_cls.return_value = resolver_instance
            resolver_instance.resolve_app.return_value = ("/path/to/myapp", True)

            # Patching 'os' in the module
            import openviper.tasks.worker

            mock_os = MagicMock()
            with patch.object(openviper.tasks.worker, "os", mock_os):
                mock_os.walk.return_value = [
                    ("/path/to/myapp", [], ["tasks.py"]),
                ]
                mock_os.path.join.side_effect = lambda *args: "/".join(args)
                mock_os.path.relpath.side_effect = lambda path, start: path.replace(start + "/", "")
                mock_os.sep = "/"

                with patch("openviper.tasks.worker.importlib.import_module") as mock_import:
                    discover_tasks()
                    mock_import.assert_any_call("myapp.tasks")


@patch("openviper.tasks.worker.configure_worker_logging_from_settings")
@patch("openviper.tasks.worker.discover_tasks")
@patch("openviper.tasks.worker.setup_broker")
@patch("openviper.tasks.worker.Worker")
@patch("signal.signal")
def test_run_worker(mock_signal, mock_worker_cls, mock_setup_broker, mock_discover, mock_log):
    mock_broker = MagicMock()
    mock_broker.get_declared_queues.return_value = {"default"}
    mock_setup_broker.return_value = mock_broker

    mock_worker_instance = MagicMock()
    mock_worker_cls.return_value = mock_worker_instance

    with patch("openviper.tasks.worker.settings") as mock_settings:
        mock_settings.TASKS = {"enabled": 1, "scheduler_enabled": 0}
        mock_settings.INSTALLED_APPS = []
        with patch("openviper.tasks.worker.time.sleep", side_effect=KeyboardInterrupt):
            run_worker()

    mock_discover.assert_called_once()
    mock_setup_broker.assert_called_once()
    mock_worker_cls.assert_called_once()
    mock_worker_instance.start.assert_called_once()
    mock_worker_instance.stop.assert_called_once()


# ---------------------------------------------------------------------------
# discover_tasks — additional paths
# ---------------------------------------------------------------------------


def test_discover_tasks_skips_openviper_internal_apps():
    """Line 80: apps starting with 'openviper.' are skipped silently."""
    with patch("openviper.tasks.worker.settings") as mock_settings:
        mock_settings.INSTALLED_APPS = ["openviper.auth", "openviper.tasks", "myapp"]

        with patch("openviper.tasks.worker.AppResolver") as mock_resolver_cls:
            resolver_instance = MagicMock()
            mock_resolver_cls.return_value = resolver_instance
            # Only 'myapp' reaches resolve_app
            resolver_instance.resolve_app.return_value = (None, False)

            with patch("openviper.tasks.worker.importlib.import_module") as mock_import:
                discover_tasks()
                # openviper.* apps were skipped; 'myapp' tried to resolve but got no path
                mock_import.assert_not_called()


def test_discover_tasks_skips_apps_with_unresolvable_path():
    """Lines 83-85: apps whose path cannot be resolved are skipped."""
    with patch("openviper.tasks.worker.settings") as mock_settings:
        mock_settings.INSTALLED_APPS = ["myapp"]

        with patch("openviper.tasks.worker.AppResolver") as mock_resolver_cls:
            resolver_instance = MagicMock()
            mock_resolver_cls.return_value = resolver_instance
            # Simulate unresolvable app path
            resolver_instance.resolve_app.return_value = ("", False)

            with patch("openviper.tasks.worker.importlib.import_module") as mock_import:
                result = discover_tasks()
                mock_import.assert_not_called()
                assert result == []


def test_discover_tasks_logs_warning_on_import_error():
    """Lines 102-103: ImportError during module import logs warning but continues."""
    import openviper.tasks.worker

    with patch("openviper.tasks.worker.settings") as mock_settings:
        mock_settings.INSTALLED_APPS = ["myapp"]

        with patch("openviper.tasks.worker.AppResolver") as mock_resolver_cls:
            resolver_instance = MagicMock()
            mock_resolver_cls.return_value = resolver_instance
            resolver_instance.resolve_app.return_value = ("/path/to/myapp", True)

            mock_os = MagicMock()
            with patch.object(openviper.tasks.worker, "os", mock_os):
                mock_os.walk.return_value = [("/path/to/myapp", [], ["tasks.py"])]
                mock_os.path.join.side_effect = lambda *a: "/".join(a)
                mock_os.path.relpath.side_effect = lambda path, start: path.replace(start + "/", "")
                mock_os.sep = "/"

                with patch(
                    "openviper.tasks.worker.importlib.import_module",
                    side_effect=ImportError("no module"),
                ):
                    result = discover_tasks()
                    # Failed import → not added to discovered list
                    assert result == []


def test_discover_tasks_extra_modules_import_error_is_logged():
    """Lines 107-112: ImportError in extra_modules is logged but doesn't raise."""
    with patch("openviper.tasks.worker.settings") as mock_settings:
        mock_settings.INSTALLED_APPS = []

        with (
            patch("openviper.tasks.worker.AppResolver"),
            patch(
                "openviper.tasks.worker.importlib.import_module",
                side_effect=ImportError("missing"),
            ),
        ):
            result = discover_tasks(extra_modules=["nonexistent.module"])
            # extra module failed → not in result
            assert result == []


# ---------------------------------------------------------------------------
# run_worker — tasks disabled path
# ---------------------------------------------------------------------------


@patch("openviper.tasks.worker.configure_worker_logging_from_settings")
def test_run_worker_disabled_returns_early(mock_log):
    """Lines 149-153: run_worker() returns immediately when tasks are disabled."""
    with patch("openviper.tasks.worker.settings") as mock_settings:
        mock_settings.TASKS = {"enabled": 0}
        mock_settings.INSTALLED_APPS = []

        with patch("openviper.tasks.worker.discover_tasks") as mock_discover:
            run_worker()
            # With tasks disabled, discover_tasks is never called
            mock_discover.assert_not_called()


# ---------------------------------------------------------------------------
# run_worker — scheduler enabled path
# ---------------------------------------------------------------------------


@patch("openviper.tasks.worker.configure_worker_logging_from_settings")
@patch("openviper.tasks.worker.discover_tasks")
@patch("openviper.tasks.worker.setup_broker")
@patch("openviper.tasks.worker.Worker")
@patch("openviper.tasks.worker.start_scheduler")
@patch("openviper.tasks.worker.stop_scheduler")
@patch("signal.signal")
def test_run_worker_with_scheduler_enabled(
    mock_signal,
    mock_stop_scheduler,
    mock_start_scheduler,
    mock_worker_cls,
    mock_setup_broker,
    mock_discover,
    mock_log,
):
    """Lines 187, 203-208: when scheduler_enabled, start/stop scheduler are called."""
    mock_broker = MagicMock()
    mock_broker.get_declared_queues.return_value = {"default"}
    mock_setup_broker.return_value = mock_broker

    mock_worker_instance = MagicMock()
    mock_worker_cls.return_value = mock_worker_instance

    with patch("openviper.tasks.worker.settings") as mock_settings:
        mock_settings.TASKS = {"enabled": 1, "scheduler_enabled": 1}
        mock_settings.INSTALLED_APPS = []
        with patch("openviper.tasks.worker.time.sleep", side_effect=KeyboardInterrupt):
            run_worker()

    mock_start_scheduler.assert_called_once()
    mock_stop_scheduler.assert_called_once()


# ---------------------------------------------------------------------------
# discover_tasks — line 92 (files in _SKIP_FILES are skipped)
# ---------------------------------------------------------------------------


def test_discover_tasks_skips_files_in_skip_files_set():
    """Line 92: filenames in _SKIP_FILES trigger continue (e.g. models.py skipped)."""
    import openviper.tasks.worker

    with patch("openviper.tasks.worker.settings") as mock_settings:
        mock_settings.INSTALLED_APPS = ["myapp"]

        with patch("openviper.tasks.worker.AppResolver") as mock_resolver_cls:
            resolver_instance = MagicMock()
            mock_resolver_cls.return_value = resolver_instance
            resolver_instance.resolve_app.return_value = ("/path/to/myapp", True)

            mock_os = MagicMock()
            with patch.object(openviper.tasks.worker, "os", mock_os):
                # models.py is in _SKIP_FILES → skipped; tasks.py → imported
                mock_os.walk.return_value = [
                    ("/path/to/myapp", [], ["models.py", "tasks.py"]),
                ]
                mock_os.path.join.side_effect = lambda *a: "/".join(a)
                mock_os.path.relpath.side_effect = lambda path, start: path.replace(start + "/", "")
                mock_os.sep = "/"

                with patch("openviper.tasks.worker.importlib.import_module") as mock_import:
                    result = discover_tasks()
                    # Only tasks.py is imported (models.py skipped via line 92 continue)
                    mock_import.assert_called_once_with("myapp.tasks")
                    assert result == ["myapp.tasks"]


# ---------------------------------------------------------------------------
# discover_tasks — lines 109-110 (extra module import success)
# ---------------------------------------------------------------------------


def test_discover_tasks_extra_modules_success():
    """Lines 109-110: extra module imported successfully is appended to result."""
    with patch("openviper.tasks.worker.settings") as mock_settings:
        mock_settings.INSTALLED_APPS = []

        with (
            patch("openviper.tasks.worker.AppResolver"),
            patch("openviper.tasks.worker.importlib.import_module") as mock_import,
        ):
            result = discover_tasks(extra_modules=["myapp.tasks"])
            mock_import.assert_called_once_with("myapp.tasks")
            assert result == ["myapp.tasks"]


# ---------------------------------------------------------------------------
# run_worker — lines 178-180 (_shutdown signal handler calls sys.exit)
# ---------------------------------------------------------------------------


@patch("openviper.tasks.worker.configure_worker_logging_from_settings")
@patch("openviper.tasks.worker.discover_tasks")
@patch("openviper.tasks.worker.setup_broker")
@patch("openviper.tasks.worker.Worker")
def test_run_worker_shutdown_signal_handler_calls_sys_exit(
    mock_worker_cls, mock_setup_broker, mock_discover, mock_log
):
    """Lines 178-180: _shutdown() logs the signal name and calls sys.exit(0)."""
    mock_broker = MagicMock()
    mock_broker.get_declared_queues.return_value = set()
    mock_setup_broker.return_value = mock_broker
    mock_worker_cls.return_value = MagicMock()

    captured_handlers: dict = {}

    def fake_signal(signum, handler):
        captured_handlers[signum] = handler

    with patch("openviper.tasks.worker.settings") as mock_settings:
        mock_settings.TASKS = {"enabled": 1, "scheduler_enabled": 0}
        mock_settings.INSTALLED_APPS = []
        with (
            patch("openviper.tasks.worker.signal.signal", side_effect=fake_signal),
            patch("openviper.tasks.worker.time.sleep", side_effect=KeyboardInterrupt),
        ):
            run_worker()

    assert signal_module.SIGINT in captured_handlers

    with patch("openviper.tasks.worker.sys.exit") as mock_exit:
        captured_handlers[signal_module.SIGINT](signal_module.SIGINT, None)

    mock_exit.assert_called_once_with(0)


# ---------------------------------------------------------------------------
# run_worker — lines 208-209 (worker.stop() exception is swallowed)
# ---------------------------------------------------------------------------


@patch("openviper.tasks.worker.configure_worker_logging_from_settings")
@patch("openviper.tasks.worker.discover_tasks")
@patch("openviper.tasks.worker.setup_broker")
@patch("openviper.tasks.worker.Worker")
@patch("signal.signal")
def test_run_worker_stop_exception_is_swallowed(
    mock_signal, mock_worker_cls, mock_setup_broker, mock_discover, mock_log
):
    """Lines 208-209: RuntimeError from worker.stop() is silently suppressed."""
    mock_broker = MagicMock()
    mock_broker.get_declared_queues.return_value = set()
    mock_setup_broker.return_value = mock_broker

    mock_worker_instance = MagicMock()
    mock_worker_instance.stop.side_effect = RuntimeError("stop failed hard")
    mock_worker_cls.return_value = mock_worker_instance

    with patch("openviper.tasks.worker.settings") as mock_settings:
        mock_settings.TASKS = {"enabled": 1, "scheduler_enabled": 0}
        mock_settings.INSTALLED_APPS = []
        with patch("openviper.tasks.worker.time.sleep", side_effect=KeyboardInterrupt):
            run_worker()  # must not raise

    mock_worker_instance.stop.assert_called_once()
