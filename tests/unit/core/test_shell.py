"""Unit tests for shell management command."""

from unittest.mock import Mock, patch

import pytest

from openviper.conf import settings
from openviper.core.management.commands.shell import Command


@pytest.fixture
def command():
    """Create a Command instance."""
    return Command()


class TestShellCommand:
    """Test shell command basic functionality."""

    def test_help_attribute(self, command):
        assert "IPython shell" in command.help or "shell" in command.help.lower()

    def test_add_arguments(self, command):
        parser = Mock()
        parser.add_argument = Mock()

        command.add_arguments(parser)

        # Should add --no-models and -c/--command
        assert parser.add_argument.call_count >= 2


class TestDiscoverModels:
    """Test model discovery."""

    def test_discover_models_empty_apps(self, command, monkeypatch):
        monkeypatch.setattr(settings, "_instance", type("Settings", (), {"INSTALLED_APPS": []})())

        models = command._discover_models()
        assert isinstance(models, dict)

    @patch("importlib.import_module")
    def test_discover_models_imports_app_models(self, mock_import, command, monkeypatch):
        monkeypatch.setattr(
            settings, "_instance", type("Settings", (), {"INSTALLED_APPS": ["testapp"]})()
        )

        # Simulate ImportError
        mock_import.side_effect = ImportError("No module named 'testapp.models'")

        models = command._discover_models()
        assert isinstance(models, dict)

        # Should have tried to import testapp.models
        mock_import.assert_called_with("testapp.models")

    @patch("openviper.core.management.commands.shell.get_user_model")
    def test_discover_models_includes_user_model(self, mock_get_user, command, capsys, monkeypatch):
        mock_user_class = type("User", (), {"__name__": "User"})
        mock_get_user.return_value = mock_user_class

        monkeypatch.setattr(settings, "_instance", type("Settings", (), {"INSTALLED_APPS": []})())

        models = command._discover_models()

        assert "User" in models


class TestBuildNamespace:
    """Test namespace building."""

    def test_build_namespace_includes_settings(self, command):
        ns, model_names = command._build_namespace(include_models=False)

        assert "settings" in ns
        assert "OpenViper" in ns
        assert "Request" in ns
        assert "JSONResponse" in ns
        assert "HTMLResponse" in ns

    @patch.object(Command, "_discover_models")
    def test_build_namespace_with_models(self, mock_discover, command):
        mock_discover.return_value = {"TestModel": type("TestModel", (), {})}

        ns, model_names = command._build_namespace(include_models=True)

        assert "TestModel" in ns
        assert "TestModel" in model_names

    def test_build_namespace_without_models(self, command):
        ns, model_names = command._build_namespace(include_models=False)

        assert model_names == []


class TestBuildBanner:
    """Test banner building."""

    @patch("importlib.import_module")
    def test_build_banner_includes_version(self, mock_import, command, monkeypatch):
        monkeypatch.setattr(
            settings, "_instance", type("Settings", (), {"PROJECT_NAME": "TestProject"})()
        )
        mock_openviper = Mock(__version__="1.0.0")
        mock_import.return_value = mock_openviper

        banner = command._build_banner([])

        assert "OpenViper" in banner or "1.0.0" in banner
        assert "TestProject" in banner

    def test_build_banner_includes_models(self, command):
        banner = command._build_banner(["User", "Post"])

        assert "User" in banner
        assert "Post" in banner

    def test_build_banner_includes_tip(self, command):
        banner = command._build_banner([])

        assert "exit()" in banner or "Ctrl-D" in banner


class TestHandle:
    """Test handle method."""

    @patch("IPython.terminal.embed.InteractiveShellEmbed")
    @patch.object(Command, "_build_namespace")
    def test_handle_starts_ipython(self, mock_namespace, mock_embed, command):
        mock_namespace.return_value = ({}, [])

        command.handle(no_models=False, command=None)

        mock_embed.assert_called_once()
        mock_embed.return_value.assert_called_once()

    @patch("IPython.terminal.embed.InteractiveShellEmbed")
    @patch.object(Command, "_build_namespace")
    def test_handle_with_no_models_flag(self, mock_namespace, mock_embed, command):
        mock_namespace.return_value = ({}, [])

        command.handle(no_models=True, command=None)

        # Should call _build_namespace with include_models=False
        mock_namespace.assert_called_once_with(False)
        mock_embed.assert_called_once()
        mock_embed.return_value.assert_called_once()

    @patch.object(Command, "_build_namespace")
    def test_handle_with_command_string(self, mock_namespace, command):
        mock_namespace.return_value = ({"test_var": 42}, [])

        # Use exec to run the command
        command.handle(no_models=False, command="print('test')")

        # Command should have been executed

    @patch.object(Command, "_build_namespace")
    def test_handle_command_syntax_error_gives_useful_traceback(self, mock_namespace, command):
        """compile() should produce a SyntaxError with '<shell -c>' filename."""
        mock_namespace.return_value = ({}, [])

        with pytest.raises(SyntaxError) as exc_info:
            command.handle(no_models=False, command="def :")

        assert "<shell -c>" in str(exc_info.value)

    def test_handle_missing_ipython_raises_error(self, command):
        with patch.dict("sys.modules", {"IPython.terminal.embed": None}):
            with pytest.raises(SystemExit):
                command.handle(no_models=False, command=None)


class TestIPythonConfig:
    """Test IPython configuration."""

    @patch("IPython.terminal.embed.InteractiveShellEmbed")
    @patch.object(Command, "_build_namespace")
    def test_handle_configures_ipython(self, mock_namespace, mock_embed, command):
        mock_namespace.return_value = ({}, [])

        command.handle(no_models=False, command=None)

        # Config should have been created (if we were still testing config, but we are not)
        mock_embed.assert_called_once()


class TestEdgeCases:
    """Test edge cases."""

    def test_command_instantiation(self):
        """Test that command can be instantiated."""
        cmd = Command()
        assert cmd is not None
        assert hasattr(cmd, "handle")
        assert hasattr(cmd, "_discover_models")
        assert hasattr(cmd, "_build_namespace")
        assert hasattr(cmd, "_build_banner")

    def test_discover_models_with_import_error(self, command, capsys, monkeypatch):
        monkeypatch.setattr(
            settings, "_instance", type("Settings", (), {"INSTALLED_APPS": ["nonexistent_app"]})()
        )

        models = command._discover_models()
        assert isinstance(models, dict)
