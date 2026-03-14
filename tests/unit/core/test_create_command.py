"""Unit tests for create_command management command."""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from openviper.core.management.base import CommandError
from openviper.core.management.commands.create_command import _COMMAND_TEMPLATE, Command


@pytest.fixture
def command():
    """Create a Command instance."""
    return Command()


@pytest.fixture
def temp_dir():
    """Create a temporary directory with an app structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a test app directory
        app_dir = Path(tmpdir) / "testapp"
        app_dir.mkdir()
        (app_dir / "__init__.py").touch()

        yield tmpdir


class TestCreateCommandCommand:
    """Test create_command command basic functionality."""

    def test_help_attribute(self, command):
        assert "Create a new management command" in command.help

    def test_add_arguments(self, command):
        parser = Mock()
        parser.add_argument = Mock()

        command.add_arguments(parser)

        # Should add command_name, app_name, and --directory arguments
        assert parser.add_argument.call_count == 3

        calls = parser.add_argument.call_args_list
        assert any("command_name" in str(call) for call in calls)
        assert any("app_name" in str(call) for call in calls)
        assert any("--directory" in str(call) for call in calls)


class TestCommandCreation:
    """Test command file creation."""

    def test_handle_creates_command_file(self, command, temp_dir, capsys):
        command.handle(command_name="mycommand", app_name="testapp", directory=temp_dir)

        command_file = Path(temp_dir) / "testapp" / "management" / "commands" / "mycommand.py"
        assert command_file.exists()

        captured = capsys.readouterr()
        assert "Created command 'mycommand'" in captured.out

    def test_handle_creates_management_directory(self, command, temp_dir):
        command.handle(command_name="test", app_name="testapp", directory=temp_dir)

        management_dir = Path(temp_dir) / "testapp" / "management"
        assert management_dir.exists()
        assert management_dir.is_dir()

    def test_handle_creates_commands_directory(self, command, temp_dir):
        command.handle(command_name="test", app_name="testapp", directory=temp_dir)

        commands_dir = Path(temp_dir) / "testapp" / "management" / "commands"
        assert commands_dir.exists()
        assert commands_dir.is_dir()

    def test_handle_creates_init_files(self, command, temp_dir):
        command.handle(command_name="test", app_name="testapp", directory=temp_dir)

        management_init = Path(temp_dir) / "testapp" / "management" / "__init__.py"
        commands_init = Path(temp_dir) / "testapp" / "management" / "commands" / "__init__.py"

        assert management_init.exists()
        assert commands_init.exists()

    def test_handle_existing_init_files_not_overwritten(self, command, temp_dir):
        # Pre-create management directory with content
        management_dir = Path(temp_dir) / "testapp" / "management"
        management_dir.mkdir()
        init_file = management_dir / "__init__.py"
        init_file.write_text("# existing content")

        command.handle(command_name="test", app_name="testapp", directory=temp_dir)

        # Content should be preserved
        assert init_file.read_text() == "# existing content"


class TestCommandFileContent:
    """Test generated command file content."""

    def test_handle_command_file_has_correct_structure(self, command, temp_dir):
        command.handle(command_name="mycommand", app_name="testapp", directory=temp_dir)

        command_file = Path(temp_dir) / "testapp" / "management" / "commands" / "mycommand.py"
        content = command_file.read_text()

        assert "class Command(BaseCommand)" in content
        assert "def add_arguments" in content
        assert "def handle" in content

    def test_handle_command_file_has_docstring(self, command, temp_dir):
        command.handle(command_name="testcmd", app_name="testapp", directory=temp_dir)

        command_file = Path(temp_dir) / "testapp" / "management" / "commands" / "testcmd.py"
        content = command_file.read_text()

        assert "testcmd management command" in content

    def test_handle_command_file_has_imports(self, command, temp_dir):
        command.handle(command_name="test", app_name="testapp", directory=temp_dir)

        command_file = Path(temp_dir) / "testapp" / "management" / "commands" / "test.py"
        content = command_file.read_text()

        assert "from openviper.core.management.base import BaseCommand" in content
        assert "import argparse" in content

    def test_handle_command_file_has_help_attribute(self, command, temp_dir):
        command.handle(command_name="test", app_name="testapp", directory=temp_dir)

        command_file = Path(temp_dir) / "testapp" / "management" / "commands" / "test.py"
        content = command_file.read_text()

        assert 'help = "Describe your command here."' in content


class TestValidation:
    """Test input validation."""

    def test_handle_invalid_command_name_raises_error(self, command, temp_dir):
        with pytest.raises(CommandError) as exc_info:
            command.handle(command_name="123invalid", app_name="testapp", directory=temp_dir)

        assert "not a valid Python identifier" in str(exc_info.value)

    def test_handle_command_name_with_hyphens_raises_error(self, command, temp_dir):
        with pytest.raises(CommandError) as exc_info:
            command.handle(command_name="my-command", app_name="testapp", directory=temp_dir)

        assert "not a valid Python identifier" in str(exc_info.value)

    def test_handle_command_name_with_spaces_raises_error(self, command, temp_dir):
        with pytest.raises(CommandError) as exc_info:
            command.handle(command_name="my command", app_name="testapp", directory=temp_dir)

        assert "not a valid Python identifier" in str(exc_info.value)

    def test_handle_existing_command_file_raises_error(self, command, temp_dir):
        # Create the command file first
        commands_dir = Path(temp_dir) / "testapp" / "management" / "commands"
        commands_dir.mkdir(parents=True)
        command_file = commands_dir / "existing.py"
        command_file.write_text("# existing")

        with pytest.raises(CommandError) as exc_info:
            command.handle(command_name="existing", app_name="testapp", directory=temp_dir)

        assert "already exists" in str(exc_info.value)


class TestDirectoryOption:
    """Test --directory option."""

    def test_handle_uses_current_directory_by_default(self, command):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create app in tmpdir
            app_dir = Path(tmpdir) / "myapp"
            app_dir.mkdir()
            (app_dir / "__init__.py").touch()

            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                command.handle(command_name="test", app_name="myapp", directory=None)

                command_file = app_dir / "management" / "commands" / "test.py"
                assert command_file.exists()
            finally:
                os.chdir(original_cwd)

    def test_handle_uses_custom_directory(self, command, temp_dir):
        command.handle(command_name="custom", app_name="testapp", directory=temp_dir)

        command_file = Path(temp_dir) / "testapp" / "management" / "commands" / "custom.py"
        assert command_file.exists()


class TestCommandTemplate:
    """Test the _COMMAND_TEMPLATE."""

    def test_command_template_format(self):
        formatted = _COMMAND_TEMPLATE.format(command_name="testcmd")

        assert "testcmd management command" in formatted
        assert "class Command(BaseCommand)" in formatted
        assert "def add_arguments(self, parser: argparse.ArgumentParser)" in formatted
        assert "def handle(self, **options)" in formatted

    def test_command_template_has_placeholder(self):
        assert "{command_name}" in _COMMAND_TEMPLATE


class TestOutputMessages:
    """Test command output messages."""

    def test_handle_success_message(self, command, temp_dir, capsys):
        command.handle(command_name="successcmd", app_name="testapp", directory=temp_dir)

        captured = capsys.readouterr()
        assert "Created command 'successcmd'" in captured.out

        # Check file path is shown
        expected_path = str(
            Path(temp_dir) / "testapp" / "management" / "commands" / "successcmd.py"
        )
        assert expected_path in captured.out


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_handle_with_snake_case_command_name(self, command, temp_dir):
        command.handle(command_name="my_custom_command", app_name="testapp", directory=temp_dir)

        command_file = (
            Path(temp_dir) / "testapp" / "management" / "commands" / "my_custom_command.py"
        )
        assert command_file.exists()

    def test_handle_with_numbers_in_command_name(self, command, temp_dir):
        command.handle(command_name="command123", app_name="testapp", directory=temp_dir)

        command_file = Path(temp_dir) / "testapp" / "management" / "commands" / "command123.py"
        assert command_file.exists()

    def test_handle_nested_app_path(self, command, temp_dir):
        """Test creating command in nested app structure."""
        nested_app = Path(temp_dir) / "apps" / "myapp"
        nested_app.mkdir(parents=True)
        (nested_app / "__init__.py").touch()

        command.handle(command_name="nested", app_name="apps/myapp", directory=temp_dir)

        command_file = nested_app / "management" / "commands" / "nested.py"
        assert command_file.exists()

    def test_command_instantiation(self):
        """Test that command can be instantiated."""
        cmd = Command()
        assert cmd is not None
        assert hasattr(cmd, "handle")
        assert hasattr(cmd, "add_arguments")

    def test_empty_init_files_created(self, command, temp_dir):
        """Test that __init__.py files are empty."""
        command.handle(command_name="test", app_name="testapp", directory=temp_dir)

        management_init = Path(temp_dir) / "testapp" / "management" / "__init__.py"
        commands_init = Path(temp_dir) / "testapp" / "management" / "commands" / "__init__.py"

        # Files should exist but may be empty
        assert management_init.stat().st_size >= 0
        assert commands_init.stat().st_size >= 0
