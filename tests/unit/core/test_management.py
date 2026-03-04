import sys
from unittest.mock import MagicMock, patch

import pytest

from openviper.core.management import _find_command, _list_commands, execute_from_command_line
from openviper.core.management.base import BaseCommand, CommandError


def test_list_commands():
    commands = _list_commands()
    assert "runserver" in commands
    assert "migrate" in commands
    assert "makemigrations" in commands
    assert "help" not in commands  # help is handled by dispatcher, not a command class


def test_find_builtin_command():
    cmd = _find_command("runserver")
    assert isinstance(cmd, BaseCommand)
    assert type(cmd).__name__ == "Command"


def test_find_unknown_command():
    with pytest.raises(CommandError, match="Unknown command"):
        _find_command("non-existent-command-xyz")


def test_execute_help(capsys):
    with pytest.raises(SystemExit) as exc:
        execute_from_command_line(["viperctl.py", "help"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "Available commands:" in captured.out
    assert "runserver" in captured.out


@patch("openviper.core.management._find_command")
def test_execute_subcommand(mock_find):
    mock_cmd = MagicMock(spec=BaseCommand)
    mock_find.return_value = mock_cmd

    with pytest.raises(SystemExit) as exc:
        execute_from_command_line(["viperctl.py", "mycmd", "--opt"])

    assert exc.value.code == 0
    mock_cmd.run_from_argv.assert_called_once_with(["viperctl.py", "mycmd", "--opt"])


def test_find_command_settings_raises_exception():
    """When settings.INSTALLED_APPS raises, installed falls back to []."""

    class RaisingSettings:
        @property
        def INSTALLED_APPS(self):
            raise RuntimeError("settings not configured")

    with patch("openviper.core.management.settings", new=RaisingSettings()):
        with pytest.raises(CommandError, match="Unknown command"):
            _find_command("non-existent-xyz")


def test_find_command_per_app_command_found():
    """Commands found in installed app's management/commands package are used."""
    mock_module = MagicMock()
    mock_cmd_instance = MagicMock(spec=BaseCommand)
    mock_module.Command.return_value = mock_cmd_instance

    with patch("openviper.core.management.settings") as ms:
        ms.INSTALLED_APPS = ["myapp"]
        with patch("openviper.core.management.importlib.import_module") as mock_import:

            def side_effect(name):
                if name == "openviper.core.management.commands.mycommand":
                    raise ModuleNotFoundError
                if name == "myapp.management.commands.mycommand":
                    return mock_module
                raise ModuleNotFoundError

            mock_import.side_effect = side_effect
            result = _find_command("mycommand")

    assert result is mock_cmd_instance


def test_execute_settings_debug_raises():
    """If settings.DEBUG raises, execution continues normally."""

    class RaisingSettings:
        @property
        def DEBUG(self):
            raise RuntimeError("settings not ready")

    mock_cmd = MagicMock(spec=BaseCommand)
    with patch("openviper.core.management.settings", new=RaisingSettings()):
        with patch("openviper.core.management._find_command", return_value=mock_cmd):
            with pytest.raises(SystemExit) as exc:
                execute_from_command_line(["viperctl.py", "somecommand"])
    assert exc.value.code == 0


def test_execute_unknown_command_exits_nonzero(capsys):
    """Unknown command prints error and exits with non-zero code."""
    with pytest.raises(SystemExit) as exc:
        execute_from_command_line(["viperctl.py", "totally-unknown-command-xyz-abc"])
    assert exc.value.code != 0
