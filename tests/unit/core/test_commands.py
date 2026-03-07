import argparse
import contextlib
import os
import sys
import tempfile
import types
from unittest.mock import MagicMock, patch

import pytest

from openviper.core.management.commands.collectstatic import Command as CollectStaticCommand
from openviper.core.management.commands.create_app import Command as CreateAppCommand
from openviper.core.management.commands.create_command import Command as CreateCommandCommand
from openviper.core.management.commands.createsuperuser import Command as CreateSuperUserCommand
from openviper.core.management.commands.makemigrations import Command as MakeMigrationsCommand
from openviper.core.management.commands.migrate import Command as MigrateCommand
from openviper.core.management.commands.runserver import Command as RunserverCommand
from openviper.core.management.commands.runworker import Command as WorkerCommand
from openviper.core.management.commands.shell import Command as ShellCommand
from openviper.core.management.commands.test import Command as TestCommand


def test_runserver_command():
    cmd = RunserverCommand()
    mock_uvicorn = MagicMock()
    with patch.dict(
        "sys.modules", {"uvicorn": mock_uvicorn}, patch.object(cmd, "_check_pending_migrations")
    ):
        cmd.handle(host="127.0.0.1", port=8000, reload=False, workers=1, app=None)
        mock_uvicorn.run.assert_called_once()

        # test reload logic
        with patch.object(cmd, "_run_with_cache_clear") as mock_clear:
            cmd.handle(host="127.0.0.1", port=8000, reload=True, workers=1, app=None)
            mock_clear.assert_called_once()


def test_shell_command():
    cmd = ShellCommand()

    mock_ipython = MagicMock()
    mock_traitlets = MagicMock()
    with patch.dict("sys.modules", {"IPython": mock_ipython, "traitlets.config": mock_traitlets}):
        cmd.handle(ipython=True, plain=False, no_models=True, command=None)
        mock_ipython.embed.assert_called_once()

    # Test command exec path (no IPython needed)
    cmd.handle(command="x = 1", no_models=True)


def test_worker_command():
    cmd = WorkerCommand()
    mock_dramatiq = MagicMock()
    with (
        patch.dict("sys.modules", {"dramatiq": mock_dramatiq}),
        patch("openviper.core.management.commands.runworker.run_worker") as mock_worker,
        patch("openviper.core.management.commands.runworker.settings") as mock_settings,
    ):
        mock_settings.TASKS = {"broker": "database"}
        cmd.handle(processes=2, threads=4, queues=None, modules=None)
        mock_worker.assert_called_once_with(processes=2, threads=4, queues=None)


def test_test_command():
    cmd = TestCommand()
    with (
        patch("openviper.core.management.commands.test.subprocess.run") as mock_run,
        patch("sys.exit") as mock_exit,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        cmd.handle(test_labels=["tests/unit"], verbosity=2, failfast=True, coverage=True)
        mock_run.assert_called_once()
        mock_exit.assert_called_once_with(0)


@patch("openviper.core.management.commands.makemigrations.os.path.exists", return_value=True)
def test_makemigrations_command(mock_exists):

    alembic_stub = MagicMock()
    with patch.dict(sys.modules, {"alembic": alembic_stub, "alembic.command": alembic_stub}):
        cmd = MakeMigrationsCommand()
        with contextlib.suppress(Exception):
            cmd.handle(message="Init", autogenerate=True, app=None)


@patch("openviper.core.management.commands.migrate.os.path.exists", return_value=True)
def test_migrate_command(mock_exists):

    alembic_stub = MagicMock()
    with patch.dict(sys.modules, {"alembic": alembic_stub, "alembic.command": alembic_stub}):
        cmd = MigrateCommand()
        with contextlib.suppress(Exception):
            cmd.handle(revision="head", app="core")


def test_collectstatic_command():
    cmd = CollectStaticCommand()
    with patch("openviper.core.management.commands.collectstatic.collect_static") as mock_collect:
        cmd.handle(no_input=True, clear=False, dry_run=False)
        mock_collect.assert_called_once()

        # Test dry_run doesn't call collect
        mock_collect.reset_mock()
        cmd.handle(no_input=True, clear=False, dry_run=True)
        mock_collect.assert_not_called()


def test_create_app_command():
    cmd = CreateAppCommand()
    with (
        patch("openviper.core.management.commands.create_app.os.makedirs") as mock_mkdir,
        patch("openviper.core.management.commands.create_app.open"),
    ):
        cmd.handle(name="testapp", directory=".")
        mock_mkdir.assert_called()


def test_create_command_command():
    cmd = CreateCommandCommand()
    with (
        patch("openviper.core.management.commands.create_command.os.makedirs") as mock_mkdir,
        patch("openviper.core.management.commands.create_command.open"),
    ):
        cmd.handle(command_name="mycmd", app_name="myapp", directory=".")
        mock_mkdir.assert_called()


def test_createsuperuser_command():
    cmd = CreateSuperUserCommand()
    with patch(
        "openviper.core.management.commands.createsuperuser.get_user_model"
    ) as mock_get_user:
        mock_model = MagicMock()
        mock_get_user.return_value = mock_model

        with patch("asyncio.run", side_effect=lambda c: c.close()) as mock_run:
            cmd.handle(username="admin", email="admin@test.com", password="pwd", no_input=True)
            mock_run.assert_called_once()


def test_all_commands_add_arguments():

    for CommandClass in [
        RunserverCommand,
        ShellCommand,
        WorkerCommand,
        TestCommand,
        MakeMigrationsCommand,
        MigrateCommand,
        CollectStaticCommand,
        CreateAppCommand,
        CreateCommandCommand,
        CreateSuperUserCommand,
    ]:
        parser = argparse.ArgumentParser()
        cmd = CommandClass()
        cmd.add_arguments(parser)


def test_shell_command_discover_models():
    cmd = ShellCommand()

    with patch("openviper.core.management.commands.shell.settings") as mock_settings:
        mock_settings.INSTALLED_APPS = ["openviper.db", "invalid.app.here"]
        models = cmd._discover_models()
        assert isinstance(models, dict)


def test_runserver_helpers():
    cmd = RunserverCommand()

    # Test _resolve_app_path
    assert cmd._resolve_app_path({"app": "custom:app"}) == "custom:app"
    with patch.dict("os.environ", {"OPENVIPER_SETTINGS_MODULE": "myproj.settings"}):
        assert cmd._resolve_app_path({}) == "myproj.asgi:app"

    # Test _check_pending_migrations without blowing up
    with patch(
        "openviper.core.management.commands.runserver.asyncio.run",
        side_effect=lambda c: [c.close(), ["app.0001_initial"]][1],
    ):
        cmd._check_pending_migrations()

    # Test _clear_pycache
    from openviper.core.management.commands.runserver import _clear_pycache

    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "__pycache__"))
        _clear_pycache(td)
        assert not os.path.exists(os.path.join(td, "__pycache__"))


def test_test_command_verbose_flag():
    cmd = TestCommand()
    with (
        patch("openviper.core.management.commands.test.subprocess.run") as mock_run,
        patch("sys.exit"),
    ):
        mock_run.return_value = MagicMock(returncode=0)
        cmd.handle(verbose=2, test_labels=[], failfast=False)
    call_args = mock_run.call_args[0][0]
    assert "-vv" in call_args


def test_test_command_py_colon_normalization():
    cmd = TestCommand()
    with (
        patch("openviper.core.management.commands.test.subprocess.run") as mock_run,
        patch("sys.exit"),
    ):
        mock_run.return_value = MagicMock(returncode=0)
        cmd.handle(verbose=0, test_labels=["mytest.py:SomeClass"], failfast=False)
    call_args = mock_run.call_args[0][0]
    assert "mytest.py::SomeClass" in call_args


def test_test_command_py_double_colon_not_altered():
    """Labels with '::' are passed through unchanged."""
    cmd = TestCommand()
    with (
        patch("openviper.core.management.commands.test.subprocess.run") as mock_run,
        patch("sys.exit"),
    ):
        mock_run.return_value = MagicMock(returncode=0)
        cmd.handle(verbose=0, test_labels=["mytest.py::SomeClass::test_foo"], failfast=False)
    call_args = mock_run.call_args[0][0]
    assert "mytest.py::SomeClass::test_foo" in call_args


# ---------------------------------------------------------------------------
# Additional shell.py command coverage
# ---------------------------------------------------------------------------


def test_shell_command_build_banner_with_models():
    cmd = ShellCommand()
    banner = cmd._build_banner(["Post", "Comment"])
    assert "Post" in banner
    assert "Comment" in banner


def test_shell_command_build_banner_without_models():
    """Banner omits Models line when model_names is empty."""
    cmd = ShellCommand()
    banner = cmd._build_banner([])
    assert "Models" not in banner


def test_shell_command_discover_models_get_user_model_exception():
    cmd = ShellCommand()
    with patch("openviper.core.management.commands.shell.settings") as ms:
        ms.INSTALLED_APPS = []
        with patch(
            "openviper.core.management.commands.shell.get_user_model",
            side_effect=RuntimeError("no user model"),
        ):
            result = cmd._discover_models()
    assert isinstance(result, dict)


def test_shell_command_ipython_import_error():
    cmd = ShellCommand()
    with (
        patch.dict("sys.modules", {"IPython": None, "traitlets.config": None}),
        pytest.raises(SystemExit, match="IPython"),
    ):
        cmd.handle(no_models=True, command=None)


def test_shell_command_discover_models_type_error(tmp_path):

    cmd = ShellCommand()

    # Build a class whose type raises TypeError on issubclass checks
    class _BadMeta(type):
        def __subclasscheck__(cls, sub):
            raise TypeError("bad issubclass")

    class BadClass(metaclass=_BadMeta):
        __module__ = "fakeapp.models"

    fake_module = types.ModuleType("fakeapp.models")
    fake_module.BadClass = BadClass  # type: ignore[attr-defined]

    # All shell-module patches must be applied BEFORE importlib.import_module
    # is patched, otherwise mock's resolution can pick up the fake module.
    with (
        patch("inspect.getmembers", return_value=[("BadClass", BadClass)]),
        patch("openviper.core.management.commands.shell.settings") as ms,
        patch(
            "openviper.core.management.commands.shell.get_user_model",
            side_effect=Exception,
        ),
    ):
        ms.INSTALLED_APPS = ["fakeapp"]
        # importlib.import_module innermost so it doesn't break other patches
        with patch(
            "openviper.core.management.commands.shell.importlib.import_module",
            return_value=fake_module,
        ):
            result = cmd._discover_models()
    # Should not raise; TypeError from issubclass is silently continued
    assert isinstance(result, dict)
