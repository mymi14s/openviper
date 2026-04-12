"""Unit tests for openviper.core.management module."""

from unittest.mock import Mock, patch

import pytest

from openviper.core.management import (
    _auto_discover_settings,
    _extract_settings_flag,
    _find_command,
    _list_commands,
    execute_from_command_line,
)
from openviper.core.management.base import BaseCommand, CommandError


class TestExecuteFromCommandLine:
    """Test execute_from_command_line function."""

    @patch("openviper.core.management._find_command")
    def test_execute_from_command_line_runs_command(self, mock_find_command):
        mock_command = Mock()
        mock_find_command.return_value = mock_command

        with pytest.raises(SystemExit) as exc_info:
            execute_from_command_line(["viperctl.py", "testcmd"])

        assert exc_info.value.code == 0
        mock_find_command.assert_called_once_with("testcmd")
        mock_command.run_from_argv.assert_called_once_with(["viperctl.py", "testcmd"])

    @patch("openviper.core.management._find_command")
    def test_execute_from_command_line_handles_command_error(self, mock_find_command, capsys):
        mock_find_command.side_effect = CommandError("Unknown command", returncode=42)

        with pytest.raises(SystemExit) as exc_info:
            execute_from_command_line(["viperctl.py", "badcmd"])

        assert exc_info.value.code == 42
        captured = capsys.readouterr()
        assert "Error: Unknown command" in captured.err

    def test_execute_from_command_line_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            execute_from_command_line(["viperctl.py", "help"])

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "Usage: viperctl.py [--settings=<module>] <command> [options]" in captured.out
        assert "Available commands:" in captured.out

    def test_execute_from_command_line_no_args(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            execute_from_command_line(["viperctl.py"])

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "Usage: viperctl.py [--settings=<module>] <command> [options]" in captured.out


class TestExtractSettingsFlag:
    """Tests for _extract_settings_flag."""

    def test_equals_syntax(self) -> None:
        value, remaining = _extract_settings_flag(
            ["viperctl.py", "--settings=project.settings.prod", "runserver"]
        )
        assert value == "project.settings.prod"
        assert remaining == ["viperctl.py", "runserver"]

    def test_space_syntax(self) -> None:
        value, remaining = _extract_settings_flag(
            ["viperctl.py", "--settings", "project.settings.dev", "migrate"]
        )
        assert value == "project.settings.dev"
        assert remaining == ["viperctl.py", "migrate"]

    def test_not_present(self) -> None:
        value, remaining = _extract_settings_flag(["viperctl.py", "runserver"])
        assert value is None
        assert remaining == ["viperctl.py", "runserver"]

    def test_flag_after_subcommand(self) -> None:
        value, remaining = _extract_settings_flag(
            ["viperctl.py", "runserver", "--settings=project.settings.prod"]
        )
        assert value == "project.settings.prod"
        assert remaining == ["viperctl.py", "runserver"]


class TestAutoDiscoverSettings:
    """Tests for _auto_discover_settings."""

    def test_discovers_package_settings(self, tmp_path) -> None:
        pkg = tmp_path / "myproject"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "settings.py").write_text("")
        (tmp_path / "viperctl.py").write_text("")

        result = _auto_discover_settings(str(tmp_path / "viperctl.py"))
        assert result == "myproject.settings"

    def test_discovers_root_settings(self, tmp_path) -> None:
        (tmp_path / "settings.py").write_text("")
        (tmp_path / "viperctl.py").write_text("")

        result = _auto_discover_settings(str(tmp_path / "viperctl.py"))
        assert result == "settings"

    def test_returns_none_when_nothing_found(self, tmp_path) -> None:
        (tmp_path / "viperctl.py").write_text("")
        result = _auto_discover_settings(str(tmp_path / "viperctl.py"))
        assert result is None

    def test_package_without_init_ignored(self, tmp_path) -> None:
        pkg = tmp_path / "myproject"
        pkg.mkdir()
        (pkg / "settings.py").write_text("")
        (tmp_path / "viperctl.py").write_text("")

        result = _auto_discover_settings(str(tmp_path / "viperctl.py"))
        assert result is None

    def test_name_match_takes_priority_over_alphabetical_first(self, tmp_path) -> None:
        """Package matching the directory name wins over alphabetically earlier packages."""
        dir_name = tmp_path.name
        # Create an alphabetically earlier package with settings.py
        earlier = tmp_path / "aaa_other"
        earlier.mkdir()
        (earlier / "__init__.py").write_text("")
        (earlier / "settings.py").write_text("")
        # Create the package matching the directory name
        matched = tmp_path / dir_name
        matched.mkdir()
        (matched / "__init__.py").write_text("")
        (matched / "settings.py").write_text("")
        (tmp_path / "viperctl.py").write_text("")

        result = _auto_discover_settings(str(tmp_path / "viperctl.py"))
        assert result == f"{dir_name}.settings"

    def test_ambiguous_packages_returns_none(self, tmp_path) -> None:
        """Multiple candidate packages with no name match → None (ambiguous)."""
        for name in ("api", "parniq"):
            pkg = tmp_path / name
            pkg.mkdir()
            (pkg / "__init__.py").write_text("")
            (pkg / "settings.py").write_text("")
        (tmp_path / "viperctl.py").write_text("")

        result = _auto_discover_settings(str(tmp_path / "viperctl.py"))
        assert result is None

    def test_discovers_settings_package_directory(self, tmp_path) -> None:
        """settings/ package directory is recognised alongside settings.py."""
        pkg = tmp_path / "myproject"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        settings_pkg = pkg / "settings"
        settings_pkg.mkdir()
        (settings_pkg / "__init__.py").write_text("")
        (tmp_path / "viperctl.py").write_text("")

        result = _auto_discover_settings(str(tmp_path / "viperctl.py"))
        assert result == "myproject.settings"

    def test_name_match_with_settings_package_directory(self, tmp_path) -> None:
        """Name-match priority applies when settings is a package directory."""
        dir_name = tmp_path.name
        matched = tmp_path / dir_name
        matched.mkdir()
        (matched / "__init__.py").write_text("")
        settings_pkg = matched / "settings"
        settings_pkg.mkdir()
        (settings_pkg / "__init__.py").write_text("")
        (tmp_path / "viperctl.py").write_text("")

        result = _auto_discover_settings(str(tmp_path / "viperctl.py"))
        assert result == f"{dir_name}.settings"


class TestExecuteFromCommandLineSettings:
    """Tests for --settings flag in execute_from_command_line."""

    @patch("openviper.core.management._find_command")
    @patch("openviper.setup")
    def test_settings_flag_sets_env_and_forces_setup(
        self, mock_setup, mock_find_command, monkeypatch
    ) -> None:
        monkeypatch.delenv("OPENVIPER_SETTINGS_MODULE", raising=False)
        mock_command = Mock()
        mock_find_command.return_value = mock_command

        with pytest.raises(SystemExit):
            execute_from_command_line(
                ["viperctl.py", "--settings=myproject.settings.prod", "migrate"]
            )

        import os

        assert os.environ.get("OPENVIPER_SETTINGS_MODULE") == "myproject.settings.prod"
        mock_setup.assert_called_with(force=True)
        mock_command.run_from_argv.assert_called_once_with(["viperctl.py", "migrate"])

    @patch("openviper.core.management._find_command")
    @patch("openviper.setup")
    def test_settings_flag_stripped_from_argv(
        self, mock_setup, mock_find_command, monkeypatch
    ) -> None:
        monkeypatch.delenv("OPENVIPER_SETTINGS_MODULE", raising=False)
        mock_command = Mock()
        mock_find_command.return_value = mock_command

        with pytest.raises(SystemExit):
            execute_from_command_line(
                ["viperctl.py", "--settings", "myproject.settings.dev", "runserver", "--port=9000"]
            )

        mock_command.run_from_argv.assert_called_once_with(
            ["viperctl.py", "runserver", "--port=9000"]
        )


class TestFindCommand:
    """Tests for _find_command function."""

    @patch("importlib.import_module")
    def test_find_builtin_command(self, mock_import):
        _find_command.cache_clear()
        mock_module = Mock()
        mock_module.Command.return_value = Mock(spec=BaseCommand)
        mock_import.return_value = mock_module

        result = _find_command("test-cmd")

        assert isinstance(result, Mock)
        mock_import.assert_called_with("openviper.core.management.commands.test_cmd")

    @patch("importlib.import_module")
    @patch("openviper.core.management.settings")
    def test_find_app_command(self, mock_settings, mock_import):
        _find_command.cache_clear()
        mock_settings.INSTALLED_APPS = ["myapp"]

        def side_effect(name):
            if name == "openviper.core.management.commands.app_cmd":
                raise ModuleNotFoundError()
            if name == "myapp.management.commands.app_cmd":
                mock_module = Mock()
                mock_module.Command.return_value = Mock(spec=BaseCommand)
                return mock_module
            raise ModuleNotFoundError()

        mock_import.side_effect = side_effect

        result = _find_command("app-cmd")
        assert isinstance(result, Mock)
        assert mock_import.call_count == 2

    @patch("openviper.core.management.settings")
    def test_find_command_not_found(self, mock_settings):
        mock_settings.INSTALLED_APPS = []
        with patch("importlib.import_module", side_effect=ModuleNotFoundError):
            with pytest.raises(CommandError) as exc_info:
                _find_command("unknown")
            assert "Unknown command" in str(exc_info.value)
            assert exc_info.value.returncode == 1

    @patch(
        "openviper.core.management.settings", spec=[]
    )  # Trigger AttributeError/Exception on settings
    def test_find_command_settings_exception(self, mock_settings):
        # settings has no INSTALLED_APPS
        with patch("importlib.import_module", side_effect=ModuleNotFoundError):
            with pytest.raises(CommandError):
                _find_command("unknown")


class TestListCommands:
    """Tests for _list_commands function."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _list_commands.cache_clear()
        yield
        _list_commands.cache_clear()

    def test_list_commands(self, monkeypatch):
        # Mock importlib.import_module to return a dummy module with __path__
        mock_module = Mock()
        mock_module.__path__ = ["path"]
        monkeypatch.setattr(
            "openviper.core.management.importlib.import_module", lambda name: mock_module
        )
        # Mock pkgutil.iter_modules to return fake command modules
        monkeypatch.setattr(
            "openviper.core.management.pkgutil.iter_modules",
            lambda path: [(None, "cmd_one", False), (None, "cmd_two", False)],
        )
        result = _list_commands()
        assert result == ["cmd-one", "cmd-two"]
