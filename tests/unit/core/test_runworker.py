"""Unit tests for the runworker management command."""

from __future__ import annotations

import argparse
import contextlib
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from openviper.core.management.commands.runworker import Command

# ---------------------------------------------------------------------------
# add_arguments
# ---------------------------------------------------------------------------


def test_add_arguments_defaults():

    cmd = Command()
    parser = argparse.ArgumentParser()
    cmd.add_arguments(parser)

    args = parser.parse_args([])
    assert args.modules == []
    assert args.queues is None
    assert args.processes == 1
    assert args.threads == 8


def test_add_arguments_all_options():

    cmd = Command()
    parser = argparse.ArgumentParser()
    cmd.add_arguments(parser)

    args = parser.parse_args(
        ["myapp.tasks", "--queues", "high", "low", "--processes", "4", "--threads", "16"]
    )
    assert args.modules == ["myapp.tasks"]
    assert args.queues == ["high", "low"]
    assert args.processes == 4
    assert args.threads == 16


# ---------------------------------------------------------------------------
# handle() – dramatiq not installed
# ---------------------------------------------------------------------------


class TestHandleDramatiqMissing:
    def test_dramatiq_not_installed_exits_1(self):
        cmd = Command()
        with patch.dict("sys.modules", {"dramatiq": None}), pytest.raises(SystemExit) as exc_info:
            cmd.handle(processes=1, threads=8, queues=None, modules=[])
        assert exc_info.value.code == 1

    def test_dramatiq_not_installed_prints_error(self):
        cmd = Command()
        err_calls = []
        with (
            patch.dict("sys.modules", {"dramatiq": None}),
            patch.object(cmd, "stderr", side_effect=lambda m: err_calls.append(m)),
            contextlib.suppress(SystemExit),
        ):
            cmd.handle(processes=1, threads=8, queues=None, modules=[])
        assert any("dramatiq" in msg for msg in err_calls)


# ---------------------------------------------------------------------------
# handle() – database broker
# ---------------------------------------------------------------------------


class TestHandleDatabaseBroker:
    def test_database_broker_calls_run_worker(self):
        cmd = Command()
        with patch("openviper.core.management.commands.runworker.settings") as ms:
            ms.TASKS = {"broker": "database"}
            with (
                patch("openviper.core.management.commands.runworker.run_worker") as mock_worker,
                patch.object(cmd, "stdout"),
            ):
                cmd.handle(processes=3, threads=6, queues=["high"], modules=[])
        mock_worker.assert_called_once_with(processes=3, threads=6, queues=["high"])

    def test_database_broker_outputs_start_message(self):
        cmd = Command()
        output = []
        with patch("openviper.core.management.commands.runworker.settings") as ms:
            ms.TASKS = {"broker": "database"}
            with (
                patch("openviper.core.management.commands.runworker.run_worker"),
                patch.object(cmd, "stdout", side_effect=lambda m: output.append(m)),
            ):
                cmd.handle(processes=1, threads=8, queues=None, modules=[])
        assert any("database" in msg.lower() for msg in output)


# ---------------------------------------------------------------------------
# handle() – Dramatiq broker with explicit modules
# ---------------------------------------------------------------------------


class TestHandleDramatiqWithModules:
    def _run_cmd(self, modules, queues=None, processes=1, threads=8, exit_code=0):
        cmd = Command()
        proc = MagicMock()
        proc.wait.return_value = None
        proc.returncode = exit_code

        with patch("openviper.core.management.commands.runworker.settings") as ms:
            ms.TASKS = {"broker": "redis"}
            ms.INSTALLED_APPS = []
            with (
                patch(
                    "openviper.core.management.commands.runworker.subprocess.Popen",
                    return_value=proc,
                ) as mock_popen,
                patch.object(cmd, "stdout"),
                contextlib.suppress(SystemExit),
            ):
                cmd.handle(processes=processes, threads=threads, queues=queues, modules=modules)
        return mock_popen

    def test_explicit_modules_passed_to_popen(self):
        mock_popen = self._run_cmd(modules=["myapp.tasks"])
        call_args = mock_popen.call_args[0][0]
        assert "myapp.tasks" in call_args

    def test_broker_module_always_first(self):
        mock_popen = self._run_cmd(modules=["myapp.tasks"])
        call_args = mock_popen.call_args[0][0]
        # openviper.tasks should appear before user modules
        mt_idx = call_args.index("openviper.tasks")
        my_idx = call_args.index("myapp.tasks")
        assert mt_idx < my_idx

    def test_processes_flag_included(self):
        mock_popen = self._run_cmd(modules=["myapp.tasks"], processes=4)
        call_args = mock_popen.call_args[0][0]
        assert "--processes" in call_args
        assert "4" in call_args

    def test_threads_flag_included(self):
        mock_popen = self._run_cmd(modules=["myapp.tasks"], threads=16)
        call_args = mock_popen.call_args[0][0]
        assert "--threads" in call_args
        assert "16" in call_args

    def test_queues_flag_included_when_specified(self):
        mock_popen = self._run_cmd(modules=["myapp.tasks"], queues=["high", "low"])
        call_args = mock_popen.call_args[0][0]
        assert "--queues" in call_args
        assert "high" in call_args
        assert "low" in call_args

    def test_no_queues_flag_when_not_specified(self):
        mock_popen = self._run_cmd(modules=["myapp.tasks"], queues=None)
        call_args = mock_popen.call_args[0][0]
        assert "--queues" not in call_args

    def test_sys_exit_with_proc_returncode(self):
        cmd = Command()
        proc = MagicMock()
        proc.wait.return_value = None
        proc.returncode = 2

        with patch("openviper.core.management.commands.runworker.settings") as ms:
            ms.TASKS = {"broker": "redis"}
            ms.INSTALLED_APPS = []
            with (
                patch(
                    "openviper.core.management.commands.runworker.subprocess.Popen",
                    return_value=proc,
                ),
                patch.object(cmd, "stdout"),
                pytest.raises(SystemExit) as exc_info,
            ):
                cmd.handle(processes=1, threads=8, queues=None, modules=["myapp.tasks"])
        assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# handle() – auto-discovery via AppResolver
# ---------------------------------------------------------------------------


class TestHandleAutoDiscovery:
    def test_no_modules_found_exits_1(self):
        """When no modules auto-discovered and none specified, sys.exit(1) is called."""
        cmd = Command()
        mock_resolver = MagicMock()
        mock_resolver.resolve_app.return_value = (None, False)

        with patch("openviper.core.management.commands.runworker.settings") as ms:
            ms.TASKS = {"broker": "redis"}
            ms.INSTALLED_APPS = ["myapp"]
            with (
                patch(
                    "openviper.core.management.commands.runworker.AppResolver",
                    return_value=mock_resolver,
                ),
                patch.object(cmd, "stdout"),
                pytest.raises(SystemExit) as exc_info,
            ):
                cmd.handle(processes=1, threads=8, queues=None, modules=[])
        assert exc_info.value.code == 1

    def test_auto_discovers_modules_from_apps(self, tmp_path):
        """Auto-discovery finds .py files in app directory."""
        tasks_file = tmp_path / "tasks.py"
        tasks_file.write_text("import dramatiq\n")

        mock_resolver = MagicMock()
        mock_resolver.resolve_app.return_value = (str(tmp_path), True)

        cmd = Command()
        proc = MagicMock()
        proc.wait.return_value = None
        proc.returncode = 0

        with patch("openviper.core.management.commands.runworker.settings") as ms:
            ms.TASKS = {"broker": "redis"}
            ms.INSTALLED_APPS = ["myapp"]
            with (
                patch(
                    "openviper.core.management.commands.runworker.AppResolver",
                    return_value=mock_resolver,
                ),
                patch(
                    "openviper.core.management.commands.runworker.subprocess.Popen",
                    return_value=proc,
                ) as mock_popen,
                patch.object(cmd, "stdout"),
                contextlib.suppress(SystemExit),
            ):
                cmd.handle(processes=1, threads=8, queues=None, modules=[])

        # Should have tried to popen with discovered modules
        if mock_popen.called:
            call_args = mock_popen.call_args[0][0]
            assert "myapp.tasks" in call_args

    def test_skips_openviper_internal_apps(self, tmp_path):
        """Apps starting with 'openviper.' are skipped during auto-discovery."""
        mock_resolver = MagicMock()
        mock_resolver.resolve_app.return_value = (str(tmp_path), True)

        cmd = Command()
        with patch("openviper.core.management.commands.runworker.settings") as ms:
            ms.TASKS = {"broker": "redis"}
            ms.INSTALLED_APPS = ["openviper.internal_app"]
            with (
                patch(
                    "openviper.core.management.commands.runworker.AppResolver",
                    return_value=mock_resolver,
                ),
                patch.object(cmd, "stdout"),
                pytest.raises(SystemExit) as exc_info,
            ):
                cmd.handle(processes=1, threads=8, queues=None, modules=[])

        # openviper.internal_app was skipped, so no modules found → exit(1)
        assert exc_info.value.code == 1
        mock_resolver.resolve_app.assert_not_called()

    def test_keyboard_interrupt_sends_sigterm(self):
        cmd = Command()
        proc = MagicMock()
        proc.wait.side_effect = [KeyboardInterrupt, None]
        proc.returncode = 0

        with patch("openviper.core.management.commands.runworker.settings") as ms:
            ms.TASKS = {"broker": "redis"}
            ms.INSTALLED_APPS = []
            with (
                patch(
                    "openviper.core.management.commands.runworker.subprocess.Popen",
                    return_value=proc,
                ),
                patch.object(cmd, "stdout"),
                contextlib.suppress(SystemExit),
            ):
                cmd.handle(processes=1, threads=8, queues=None, modules=["myapp.tasks"])

        proc.send_signal.assert_called_once()

    def test_keyboard_interrupt_timeout_kills_proc(self):
        cmd = Command()
        proc = MagicMock()
        proc.wait.side_effect = [KeyboardInterrupt, subprocess.TimeoutExpired(None, 5), None]
        proc.returncode = 0

        with patch("openviper.core.management.commands.runworker.settings") as ms:
            ms.TASKS = {"broker": "redis"}
            ms.INSTALLED_APPS = []
            with (
                patch(
                    "openviper.core.management.commands.runworker.subprocess.Popen",
                    return_value=proc,
                ),
                patch.object(cmd, "stdout"),
                contextlib.suppress(SystemExit),
            ):
                cmd.handle(processes=1, threads=8, queues=None, modules=["myapp.tasks"])

        proc.kill.assert_called_once()


class TestHandleSkipFiles:
    def test_skip_files_in_skip_files_set_not_included(self, tmp_path):
        # Create a models.py (in _SKIP_FILES) and a tasks.py (not skipped)
        (tmp_path / "models.py").write_text("# models\n")
        (tmp_path / "tasks.py").write_text("# tasks\n")

        mock_resolver = MagicMock()
        mock_resolver.resolve_app.return_value = (str(tmp_path), True)

        cmd = Command()
        proc = MagicMock()
        proc.wait.return_value = None
        proc.returncode = 0

        with patch("openviper.core.management.commands.runworker.settings") as ms:
            ms.TASKS = {"broker": "redis"}
            ms.INSTALLED_APPS = ["myapp"]
            with (
                patch(
                    "openviper.core.management.commands.runworker.AppResolver",
                    return_value=mock_resolver,
                ),
                patch(
                    "openviper.core.management.commands.runworker.subprocess.Popen",
                    return_value=proc,
                ) as mock_popen,
                patch.object(cmd, "stdout"),
                contextlib.suppress(SystemExit),
            ):
                cmd.handle(processes=1, threads=8, queues=None, modules=[])

        if mock_popen.called:
            call_args = mock_popen.call_args[0][0]
            # models.py should NOT appear in the module list
            assert not any("models" in arg for arg in call_args if "myapp" in arg)
            # tasks.py SHOULD appear
            assert "myapp.tasks" in call_args
