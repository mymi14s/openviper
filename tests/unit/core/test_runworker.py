"""Unit tests for runworker management command."""

import importlib
import signal
import subprocess
import sys
from unittest.mock import Mock, patch

import pytest

from openviper.core.management.commands.runworker import Command


@pytest.fixture
def command():
    """Create a Command instance."""
    return Command()


class TestRunWorkerCommand:
    """Test runworker command basic functionality."""

    def test_help_attribute(self, command):
        assert "Dramatiq" in command.help or "task worker" in command.help

    def test_add_arguments(self, command):
        parser = Mock()
        parser.add_argument = Mock()

        command.add_arguments(parser)

        # Should add modules, --queues, --threads, --processes
        assert parser.add_argument.call_count >= 4


class TestDramatiqImport:
    """Test dramatiq import handling."""

    def test_handle_missing_dramatiq_exits(self, command, capsys):
        """Test that missing dramatiq exits with error."""
        original_import_module = importlib.import_module

        def mock_import_module(name: str, *args, **kwargs):
            if name == "dramatiq":
                raise ImportError("No module named 'dramatiq'")
            return original_import_module(name, *args, **kwargs)

        with patch(
            "openviper.core.management.commands.runworker.importlib.import_module",
            side_effect=mock_import_module,
        ):
            with pytest.raises(SystemExit) as exc_info:
                command.handle(modules=[], queues=None, threads=8, processes=1)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "dramatiq is required" in captured.err


class TestDatabaseBroker:
    """Test database broker mode."""

    def test_handle_database_broker_runs_in_process(self, command, capsys):
        """Test that database broker runs worker in-process."""
        mock_dramatiq = Mock()
        mock_settings = Mock()
        mock_settings.TASKS = {"broker": "database"}

        mock_run_worker = Mock()

        with patch.dict(sys.modules, {"dramatiq": mock_dramatiq}):
            with patch("openviper.core.management.commands.runworker.settings", mock_settings):
                with patch(
                    "openviper.core.management.commands.runworker.run_worker",
                    mock_run_worker,
                ):
                    command.handle(modules=[], queues=None, threads=8, processes=1)

        mock_run_worker.assert_called_once_with(processes=1, threads=8, queues=None)

        captured = capsys.readouterr()
        assert "database worker" in captured.out


class TestRedisBroker:
    """Test Redis/RabbitMQ broker mode."""

    def test_handle_redis_broker_spawns_subprocess(self, command, capsys):
        """Test that Redis broker spawns dramatiq subprocess."""
        mock_dramatiq = Mock()
        mock_settings = Mock()
        mock_settings.TASKS = {"broker": "redis"}
        mock_settings.INSTALLED_APPS = []

        mock_resolver = Mock()
        mock_resolver.resolve_app = Mock(return_value=(None, False))

        mock_proc = Mock()
        mock_proc.returncode = 0
        mock_proc.wait = Mock()

        with patch.dict(sys.modules, {"dramatiq": mock_dramatiq}):
            with patch("openviper.core.management.commands.runworker.settings", mock_settings):
                with patch(
                    "openviper.core.management.commands.runworker.AppResolver",
                    return_value=mock_resolver,
                ):
                    with patch(
                        "openviper.core.management.commands.runworker.subprocess.Popen",
                        return_value=mock_proc,
                    ) as mock_popen:
                        command.handle(modules=["myapp.tasks"], queues=None, threads=8, processes=1)

        mock_popen.assert_called_once()


class TestModuleDiscovery:
    """Test task module auto-discovery."""

    def test_handle_discovers_task_modules(self, command):
        """Test that modules are discovered from INSTALLED_APPS."""
        mock_dramatiq = Mock()
        mock_settings = Mock()
        mock_settings.TASKS = {"broker": "redis"}
        mock_settings.INSTALLED_APPS = ["testapp"]

        mock_resolver = Mock()
        mock_resolver.resolve_app = Mock(return_value=("/fake/testapp", True))

        with patch.dict(sys.modules, {"dramatiq": mock_dramatiq}):
            with patch("openviper.core.management.commands.runworker.settings", mock_settings):
                with patch(
                    "openviper.core.management.commands.runworker.AppResolver",
                    return_value=mock_resolver,
                ):
                    with patch(
                        "openviper.core.management.commands.runworker.os.walk",
                        return_value=[],
                    ):
                        # No modules discovered, should exit
                        with pytest.raises(SystemExit) as exc_info:
                            command.handle(modules=[], queues=None, threads=8, processes=1)

                        assert exc_info.value.code == 1

    @patch("openviper.core.management.commands.runworker.subprocess.Popen")
    def test_handle_discovers_task_modules_ignores_openviper_and_unfound(self, mock_popen, command):
        """Test module discovery filters correctly."""
        mock_dramatiq = Mock()
        mock_settings = Mock()
        mock_settings.TASKS = {"broker": "redis"}
        mock_settings.INSTALLED_APPS = ["openviper.auth", "notfound", "testapp"]

        mock_resolver = Mock()

        def mock_resolve(app):
            if app == "notfound":
                return None, False
            if app == "testapp":
                return "/fake/testapp", True
            return None, False

        mock_resolver.resolve_app.side_effect = mock_resolve

        mock_proc = Mock()
        mock_proc.returncode = 0
        mock_proc.wait = Mock()
        mock_popen.return_value = mock_proc

        def mock_walk(path):
            if path == "/fake/testapp":
                yield ("/fake/testapp", [], ["tasks.py", "other_tasks.py", "not_a_task.txt"])
            else:
                yield (path, [], [])

        with patch.dict(sys.modules, {"dramatiq": mock_dramatiq}):
            with patch("openviper.core.management.commands.runworker.settings", mock_settings):
                with patch(
                    "openviper.core.management.commands.runworker.AppResolver",
                    return_value=mock_resolver,
                ):
                    with patch(
                        "openviper.core.management.commands.runworker.os.walk",
                        side_effect=mock_walk,
                    ):
                        command.handle(modules=[], queues=None, threads=8, processes=1)

        call_args = mock_popen.call_args[0][0]
        assert "testapp.tasks" in call_args
        assert "testapp.other_tasks" in call_args


class TestCommandLineBuilding:
    """Test command line argument building."""

    def test_handle_builds_command_with_threads(self, command):
        """Test that threads argument is passed to dramatiq."""
        mock_dramatiq = Mock()
        mock_settings = Mock()
        mock_settings.TASKS = {"broker": "redis"}
        mock_settings.INSTALLED_APPS = []

        mock_resolver = Mock()

        mock_proc = Mock()
        mock_proc.returncode = 0
        mock_proc.wait = Mock()

        with patch.dict(sys.modules, {"dramatiq": mock_dramatiq}):
            with patch("openviper.core.management.commands.runworker.settings", mock_settings):
                with patch(
                    "openviper.core.management.commands.runworker.AppResolver",
                    return_value=mock_resolver,
                ):
                    with patch(
                        "openviper.core.management.commands.runworker.subprocess.Popen",
                        return_value=mock_proc,
                    ) as mock_popen:
                        command.handle(modules=["test"], queues=None, threads=4, processes=1)

        call_args = mock_popen.call_args[0][0]
        assert "--threads" in call_args
        assert "4" in call_args

    def test_handle_builds_command_with_queues(self, command):
        """Test that queues argument is passed to dramatiq."""
        mock_dramatiq = Mock()
        mock_settings = Mock()
        mock_settings.TASKS = {"broker": "redis"}
        mock_settings.INSTALLED_APPS = []

        mock_resolver = Mock()

        mock_proc = Mock()
        mock_proc.returncode = 0
        mock_proc.wait = Mock()

        with patch.dict(sys.modules, {"dramatiq": mock_dramatiq}):
            with patch("openviper.core.management.commands.runworker.settings", mock_settings):
                with patch(
                    "openviper.core.management.commands.runworker.AppResolver",
                    return_value=mock_resolver,
                ):
                    with patch(
                        "openviper.core.management.commands.runworker.subprocess.Popen",
                        return_value=mock_proc,
                    ) as mock_popen:
                        command.handle(
                            modules=["test"], queues=["high", "low"], threads=8, processes=1
                        )

        call_args = mock_popen.call_args[0][0]
        assert "--queues" in call_args
        assert "high" in call_args
        assert "low" in call_args


class TestSignalHandling:
    """Test signal handling for subprocess."""

    def test_handle_handles_keyboard_interrupt(self, command):
        """Test that KeyboardInterrupt sends SIGTERM to subprocess."""
        mock_dramatiq = Mock()
        mock_settings = Mock()
        mock_settings.TASKS = {"broker": "redis"}
        mock_settings.INSTALLED_APPS = []

        mock_resolver = Mock()

        mock_proc = Mock()
        mock_proc.wait = Mock(side_effect=[KeyboardInterrupt, None])
        mock_proc.send_signal = Mock()
        mock_proc.returncode = 0

        with patch.dict(sys.modules, {"dramatiq": mock_dramatiq}):
            with patch("openviper.core.management.commands.runworker.settings", mock_settings):
                with patch(
                    "openviper.core.management.commands.runworker.AppResolver",
                    return_value=mock_resolver,
                ):
                    with patch(
                        "openviper.core.management.commands.runworker.subprocess.Popen",
                        return_value=mock_proc,
                    ):
                        command.handle(modules=["test"], queues=None, threads=8, processes=1)

        mock_proc.send_signal.assert_called_with(signal.SIGTERM)

    def test_handle_handles_keyboard_interrupt_with_timeout(self, command):
        """Test KeyboardInterrupt with subprocess timeout."""
        mock_dramatiq = Mock()
        mock_settings = Mock()
        mock_settings.TASKS = {"broker": "redis"}
        mock_settings.INSTALLED_APPS = []

        mock_resolver = Mock()

        mock_proc = Mock()
        # Raise KeyboardInterrupt, then timeout, then finish
        mock_proc.wait = Mock(
            side_effect=[
                KeyboardInterrupt,
                subprocess.TimeoutExpired(cmd="dramatiq", timeout=5),
                None,
            ]
        )
        mock_proc.send_signal = Mock()
        mock_proc.kill = Mock()
        mock_proc.returncode = 0

        with patch.dict(sys.modules, {"dramatiq": mock_dramatiq}):
            with patch("openviper.core.management.commands.runworker.settings", mock_settings):
                with patch(
                    "openviper.core.management.commands.runworker.AppResolver",
                    return_value=mock_resolver,
                ):
                    with patch(
                        "openviper.core.management.commands.runworker.subprocess.Popen",
                        return_value=mock_proc,
                    ):
                        command.handle(modules=["test"], queues=None, threads=8, processes=1)

        mock_proc.send_signal.assert_called_with(signal.SIGTERM)
        mock_proc.kill.assert_called_once()


class TestEdgeCases:
    """Test edge cases."""

    def test_command_instantiation(self):
        """Test that command can be instantiated."""
        cmd = Command()
        assert cmd is not None
        assert hasattr(cmd, "handle")
        assert hasattr(cmd, "add_arguments")

    def test_handle_default_broker_is_redis(self, command):
        """Test that default broker is redis when not specified."""
        mock_dramatiq = Mock()
        mock_settings = Mock()
        mock_settings.TASKS = {}
        mock_settings.INSTALLED_APPS = []

        mock_resolver = Mock()

        with patch.dict(sys.modules, {"dramatiq": mock_dramatiq}):
            with patch("openviper.core.management.commands.runworker.settings", mock_settings):
                with patch(
                    "openviper.core.management.commands.runworker.AppResolver",
                    return_value=mock_resolver,
                ):
                    with patch("openviper.core.management.commands.runworker.subprocess.Popen"):
                        # No modules found, should exit
                        with pytest.raises(SystemExit):
                            command.handle(modules=[], queues=None, threads=8, processes=1)

    def test_handle_nonzero_return_code(self, command):
        """Test exit with subprocess return code."""
        mock_dramatiq = Mock()
        mock_settings = Mock()
        mock_settings.TASKS = {"broker": "redis"}
        mock_settings.INSTALLED_APPS = []

        mock_resolver = Mock()

        mock_proc = Mock()
        mock_proc.wait = Mock()
        mock_proc.returncode = 42

        with patch.dict(sys.modules, {"dramatiq": mock_dramatiq}):
            with patch("openviper.core.management.commands.runworker.settings", mock_settings):
                with patch(
                    "openviper.core.management.commands.runworker.AppResolver",
                    return_value=mock_resolver,
                ):
                    with patch(
                        "openviper.core.management.commands.runworker.subprocess.Popen",
                        return_value=mock_proc,
                    ):
                        with pytest.raises(SystemExit) as exc_info:
                            command.handle(modules=["test"], queues=None, threads=8, processes=1)

                        assert exc_info.value.code == 42
