"""Unit tests for collectstatic management command."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from openviper.core.management.commands.collectstatic import Command


@pytest.fixture
def command():
    """Create a Command instance."""
    return Command()


@pytest.fixture
def temp_dirs():
    """Create temporary source and destination directories."""
    with tempfile.TemporaryDirectory() as source_dir:
        with tempfile.TemporaryDirectory() as static_root:
            # Create some test files
            source_path = Path(source_dir)
            (source_path / "style.css").write_text("body { margin: 0; }")
            (source_path / "script.js").write_text("console.log('test');")

            subdir = source_path / "images"
            subdir.mkdir()
            (subdir / "logo.png").write_bytes(b"fake-png-data")

            yield source_dir, static_root


class TestCollectStaticCommand:
    """Test collectstatic command basic functionality."""

    def test_help_attribute(self, command):
        assert "Copy static files" in command.help
        assert "STATICFILES_DIRS" in command.help
        assert "STATIC_ROOT" in command.help

    def test_add_arguments(self, command):
        parser = Mock()
        parser.add_argument = Mock()

        command.add_arguments(parser)

        # Should add --no-input, --clear, --dry-run arguments
        assert parser.add_argument.call_count == 3

        calls = parser.add_argument.call_args_list
        assert any("--no-input" in str(call) for call in calls)
        assert any("--clear" in str(call) for call in calls)
        assert any("--dry-run" in str(call) for call in calls)


class TestDryRun:
    """Test dry-run functionality."""

    @patch("openviper.core.management.commands.collectstatic.settings")
    def test_handle_dry_run(self, mock_settings, command, capsys):
        mock_settings.STATIC_ROOT = "static"
        mock_settings.STATICFILES_DIRS = ["static_source"]

        command.handle(dry_run=True, no_input=True, clear=False)

        captured = capsys.readouterr()
        assert "Would collect static files" in captured.out
        assert "static_source" in captured.out
        assert "static" in captured.out

    @patch("openviper.core.management.commands.collectstatic.settings")
    @patch("openviper.core.management.commands.collectstatic.collect_static")
    def test_handle_dry_run_does_not_collect(self, mock_collect_static, mock_settings, command):
        mock_settings.STATIC_ROOT = "static"
        mock_settings.STATICFILES_DIRS = ["static_source"]

        command.handle(dry_run=True, no_input=True, clear=False)

        # collect_static should not be called
        mock_collect_static.assert_not_called()


class TestNoInput:
    """Test no-input mode."""

    @patch("openviper.core.management.commands.collectstatic.settings")
    @patch("openviper.core.management.commands.collectstatic.collect_static")
    def test_handle_no_input_proceeds(self, mock_collect_static, mock_settings, command, capsys):
        mock_settings.STATIC_ROOT = "static"
        mock_settings.STATICFILES_DIRS = ["static_source"]
        mock_collect_static.return_value = 10

        command.handle(no_input=True, clear=False, dry_run=False)

        # collect_static should be called
        mock_collect_static.assert_called_once_with(["static_source"], "static", clear=False)

        captured = capsys.readouterr()
        assert "Collected 10 static file(s)" in captured.out

    @patch("openviper.core.management.commands.collectstatic.settings")
    @patch("openviper.core.management.commands.collectstatic.collect_static")
    @patch("builtins.input", return_value="yes")
    def test_handle_with_input_confirmation_yes(
        self, mock_input, mock_collect_static, mock_settings, command
    ):
        mock_settings.STATIC_ROOT = "static"
        mock_settings.STATICFILES_DIRS = ["static_source"]
        mock_collect_static.return_value = 5

        command.handle(no_input=False, clear=False, dry_run=False)

        # Should prompt for confirmation
        mock_input.assert_called_once()

        # collect_static should be called
        mock_collect_static.assert_called_once()

    @patch("openviper.core.management.commands.collectstatic.settings")
    @patch("openviper.core.management.commands.collectstatic.collect_static")
    @patch("builtins.input", return_value="no")
    def test_handle_with_input_confirmation_no(
        self, mock_input, mock_collect_static, mock_settings, command, capsys
    ):
        mock_settings.STATIC_ROOT = "static"
        mock_settings.STATICFILES_DIRS = ["static_source"]

        command.handle(no_input=False, clear=False, dry_run=False)

        # Should prompt for confirmation
        mock_input.assert_called_once()

        # collect_static should NOT be called
        mock_collect_static.assert_not_called()

        captured = capsys.readouterr()
        assert "Aborted" in captured.out

    @patch("openviper.core.management.commands.collectstatic.settings")
    @patch("openviper.core.management.commands.collectstatic.collect_static")
    @patch("builtins.input", return_value="y")
    def test_handle_with_input_confirmation_y(
        self, mock_input, mock_collect_static, mock_settings, command
    ):
        mock_settings.STATIC_ROOT = "static"
        mock_settings.STATICFILES_DIRS = ["static_source"]
        mock_collect_static.return_value = 3

        command.handle(no_input=False, clear=False, dry_run=False)

        # 'y' should be accepted
        mock_collect_static.assert_called_once()


class TestClearOption:
    """Test --clear option."""

    @patch("openviper.core.management.commands.collectstatic.settings")
    @patch("openviper.core.management.commands.collectstatic.collect_static")
    def test_handle_with_clear(self, mock_collect_static, mock_settings, command):
        mock_settings.STATIC_ROOT = "static"
        mock_settings.STATICFILES_DIRS = ["static_source"]
        mock_collect_static.return_value = 10

        command.handle(no_input=True, clear=True, dry_run=False)

        # collect_static should be called with clear=True
        mock_collect_static.assert_called_once_with(["static_source"], "static", clear=True)

    @patch("openviper.core.management.commands.collectstatic.settings")
    @patch("openviper.core.management.commands.collectstatic.collect_static")
    def test_handle_without_clear(self, mock_collect_static, mock_settings, command):
        mock_settings.STATIC_ROOT = "static"
        mock_settings.STATICFILES_DIRS = ["static_source"]
        mock_collect_static.return_value = 10

        command.handle(no_input=True, clear=False, dry_run=False)

        # collect_static should be called with clear=False
        mock_collect_static.assert_called_once_with(["static_source"], "static", clear=False)


class TestSettingsRetrieval:
    """Test settings retrieval with defaults."""

    @patch("openviper.core.management.commands.collectstatic.settings")
    @patch("openviper.core.management.commands.collectstatic.collect_static")
    def test_handle_uses_settings_static_root(self, mock_collect_static, mock_settings, command):
        mock_settings.STATIC_ROOT = "custom_static"
        mock_settings.STATICFILES_DIRS = ["source"]
        mock_collect_static.return_value = 5

        command.handle(no_input=True, clear=False, dry_run=False)

        mock_collect_static.assert_called_once_with(["source"], "custom_static", clear=False)

    @patch("openviper.core.management.commands.collectstatic.settings")
    @patch("openviper.core.management.commands.collectstatic.collect_static")
    def test_handle_uses_default_static_root(self, mock_collect_static, mock_settings, command):
        # Use spec to allow getattr with defaults
        del mock_settings.STATIC_ROOT
        mock_settings.STATICFILES_DIRS = ["source"]

        mock_collect_static.return_value = 5

        command.handle(no_input=True, clear=False, dry_run=False)

        # Should use default "static" when STATIC_ROOT is not set
        # The command uses getattr(settings, "STATIC_ROOT", "static")
        mock_collect_static.assert_called_once_with(["source"], "static", clear=False)

    @patch("openviper.core.management.commands.collectstatic.settings")
    @patch("openviper.core.management.commands.collectstatic.collect_static")
    def test_handle_uses_settings_staticfiles_dirs(
        self, mock_collect_static, mock_settings, command
    ):
        mock_settings.STATIC_ROOT = "static"
        mock_settings.STATICFILES_DIRS = ["dir1", "dir2", "dir3"]
        mock_collect_static.return_value = 15

        command.handle(no_input=True, clear=False, dry_run=False)

        mock_collect_static.assert_called_once_with(["dir1", "dir2", "dir3"], "static", clear=False)


class TestSuccessOutput:
    """Test success message output."""

    @patch("openviper.core.management.commands.collectstatic.settings")
    @patch("openviper.core.management.commands.collectstatic.collect_static")
    def test_handle_success_message(self, mock_collect_static, mock_settings, command, capsys):
        mock_settings.STATIC_ROOT = "static"
        mock_settings.STATICFILES_DIRS = ["source"]
        mock_collect_static.return_value = 42

        command.handle(no_input=True, clear=False, dry_run=False)

        captured = capsys.readouterr()
        assert "Collected 42 static file(s)" in captured.out
        assert "static" in captured.out

    @patch("openviper.core.management.commands.collectstatic.settings")
    @patch("openviper.core.management.commands.collectstatic.collect_static")
    def test_handle_zero_files(self, mock_collect_static, mock_settings, command, capsys):
        mock_settings.STATIC_ROOT = "static"
        mock_settings.STATICFILES_DIRS = ["source"]
        mock_collect_static.return_value = 0

        command.handle(no_input=True, clear=False, dry_run=False)

        captured = capsys.readouterr()
        assert "Collected 0 static file(s)" in captured.out


class TestInputVariations:
    """Test various input variations."""

    @patch("openviper.core.management.commands.collectstatic.settings")
    @patch("openviper.core.management.commands.collectstatic.collect_static")
    @patch("builtins.input", return_value="YES")
    def test_handle_input_case_insensitive(
        self, mock_input, mock_collect_static, mock_settings, command
    ):
        mock_settings.STATIC_ROOT = "static"
        mock_settings.STATICFILES_DIRS = ["source"]
        mock_collect_static.return_value = 5

        command.handle(no_input=False, clear=False, dry_run=False)

        # 'YES' (uppercase) should be accepted
        mock_collect_static.assert_called_once()

    @patch("openviper.core.management.commands.collectstatic.settings")
    @patch("openviper.core.management.commands.collectstatic.collect_static")
    @patch("builtins.input", return_value="  yes  ")
    def test_handle_input_strips_whitespace(
        self, mock_input, mock_collect_static, mock_settings, command
    ):
        mock_settings.STATIC_ROOT = "static"
        mock_settings.STATICFILES_DIRS = ["source"]
        mock_collect_static.return_value = 5

        command.handle(no_input=False, clear=False, dry_run=False)

        # Whitespace should be stripped
        mock_collect_static.assert_called_once()

    @patch("openviper.core.management.commands.collectstatic.settings")
    @patch("openviper.core.management.commands.collectstatic.collect_static")
    @patch("builtins.input", return_value="maybe")
    def test_handle_input_invalid_response(
        self, mock_input, mock_collect_static, mock_settings, command, capsys
    ):
        mock_settings.STATIC_ROOT = "static"
        mock_settings.STATICFILES_DIRS = ["source"]

        command.handle(no_input=False, clear=False, dry_run=False)

        # Invalid response should abort
        mock_collect_static.assert_not_called()

        captured = capsys.readouterr()
        assert "Aborted" in captured.out


class TestEdgeCases:
    """Test edge cases and error conditions."""

    @patch("openviper.core.management.commands.collectstatic.settings")
    @patch("openviper.core.management.commands.collectstatic.collect_static")
    def test_handle_empty_staticfiles_dirs(self, mock_collect_static, mock_settings, command):
        mock_settings.STATIC_ROOT = "static"
        mock_settings.STATICFILES_DIRS = []
        mock_collect_static.return_value = 0

        command.handle(no_input=True, clear=False, dry_run=False)

        mock_collect_static.assert_called_once_with([], "static", clear=False)

    def test_command_instantiation(self):
        """Test that command can be instantiated."""
        cmd = Command()
        assert cmd is not None
        assert hasattr(cmd, "handle")
        assert hasattr(cmd, "add_arguments")

    @patch("openviper.core.management.commands.collectstatic.settings")
    @patch("builtins.input", return_value="yes")
    def test_handle_confirmation_prompt_content(self, mock_input, mock_settings, command):
        mock_settings.STATIC_ROOT = "/dest/static"
        mock_settings.STATICFILES_DIRS = ["/source/static"]

        with patch("openviper.core.management.commands.collectstatic.collect_static"):
            command.handle(no_input=False, clear=False, dry_run=False)

        # Check that the prompt contains relevant information
        call_args = mock_input.call_args[0][0]
        assert "/source/static" in call_args or "source" in call_args
        assert "/dest/static" in call_args or "static" in call_args
        assert "Continue?" in call_args or "yes" in call_args.lower()
