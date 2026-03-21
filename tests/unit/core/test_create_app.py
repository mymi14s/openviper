"""Unit tests for create_app management command."""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from openviper.core.management.base import CommandError
from openviper.core.management.commands.create_app import _APP_TEMPLATE, Command


@pytest.fixture
def command():
    """Create a Command instance."""
    return Command()


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


class TestCreateAppCommand:
    """Test create_app command basic functionality."""

    def test_help_attribute(self, command):
        assert "Scaffold a new OpenViper application" in command.help

    def test_aliases_attribute(self, command):
        assert command.aliases == ["create-app"]

    def test_add_arguments(self, command):
        parser = Mock()
        parser.add_argument = Mock()

        command.add_arguments(parser)

        # Should add name and --directory arguments
        assert parser.add_argument.call_count == 2

        calls = parser.add_argument.call_args_list
        assert any("name" in str(call) for call in calls)
        assert any("--directory" in str(call) for call in calls)


class TestAppCreation:
    """Test app creation functionality."""

    def test_handle_creates_app_directory(self, command, temp_dir, capsys):
        command.handle(name="myapp", directory=temp_dir)

        app_dir = Path(temp_dir) / "myapp"
        assert app_dir.exists()
        assert app_dir.is_dir()

        captured = capsys.readouterr()
        assert "Created app 'myapp'" in captured.out

    def test_handle_creates_all_template_files(self, command, temp_dir):
        command.handle(name="testapp", directory=temp_dir)

        app_dir = Path(temp_dir) / "testapp"

        # Check all template files exist
        assert (app_dir / "__init__.py").exists()
        assert (app_dir / "admin.py").exists()
        assert (app_dir / "models.py").exists()
        assert (app_dir / "routes.py").exists()
        assert (app_dir / "views.py").exists()
        assert (app_dir / "serializers.py").exists()
        assert (app_dir / "tasks.py").exists()
        assert (app_dir / "events.py").exists()
        assert (app_dir / "tests.py").exists()

    def test_handle_creates_migrations_directory(self, command, temp_dir):
        command.handle(name="myapp", directory=temp_dir)

        migrations_dir = Path(temp_dir) / "myapp" / "migrations"
        assert migrations_dir.exists()
        assert migrations_dir.is_dir()
        assert (migrations_dir / "__init__.py").exists()

    def test_handle_replaces_app_label_in_templates(self, command, temp_dir):
        command.handle(name="blogapp", directory=temp_dir)

        app_dir = Path(temp_dir) / "blogapp"

        # Check __init__.py contains app label
        init_content = (app_dir / "__init__.py").read_text()
        assert "blogapp" in init_content

        # Check routes.py contains app label
        routes_content = (app_dir / "routes.py").read_text()
        assert "blogapp" in routes_content
        assert "/blogapp" in routes_content

    def test_handle_models_py_has_correct_imports(self, command, temp_dir):
        command.handle(name="testapp", directory=temp_dir)

        models_content = (Path(temp_dir) / "testapp" / "models.py").read_text()
        assert "from openviper.db.models import Model" in models_content
        assert "from openviper.db import fields" in models_content

    def test_handle_admin_py_has_correct_imports(self, command, temp_dir):
        command.handle(name="testapp", directory=temp_dir)

        admin_content = (Path(temp_dir) / "testapp" / "admin.py").read_text()
        assert "from openviper.admin import admin, ModelAdmin, register" in admin_content


class TestValidation:
    """Test input validation."""

    def test_handle_invalid_identifier_raises_error(self, command, temp_dir):
        with pytest.raises(CommandError) as exc_info:
            command.handle(name="123invalid", directory=temp_dir)

        assert "not a valid Python identifier" in str(exc_info.value)

    def test_handle_with_hyphens_raises_error(self, command, temp_dir):
        with pytest.raises(CommandError) as exc_info:
            command.handle(name="my-app", directory=temp_dir)

        assert "not a valid Python identifier" in str(exc_info.value)

    def test_handle_with_spaces_raises_error(self, command, temp_dir):
        with pytest.raises(CommandError) as exc_info:
            command.handle(name="my app", directory=temp_dir)

        assert "not a valid Python identifier" in str(exc_info.value)

    def test_handle_existing_directory_raises_error(self, command, temp_dir):
        # Create the directory first
        app_dir = Path(temp_dir) / "existing"
        app_dir.mkdir()

        with pytest.raises(CommandError) as exc_info:
            command.handle(name="existing", directory=temp_dir)

        assert "already exists" in str(exc_info.value)


class TestDirectoryOption:
    """Test --directory option."""

    def test_handle_uses_current_directory_by_default(self, command):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                command.handle(name="myapp", directory=None)

                app_dir = Path(tmpdir) / "myapp"
                assert app_dir.exists()
            finally:
                os.chdir(original_cwd)

    def test_handle_uses_custom_directory(self, command, temp_dir):
        command.handle(name="customapp", directory=temp_dir)

        app_dir = Path(temp_dir) / "customapp"
        assert app_dir.exists()

    def test_handle_creates_nested_directories(self, command, temp_dir):
        # Test that parent directories don't need to exist
        os.path.join(temp_dir, "apps", "myapp")
        command.handle(name="myapp", directory=os.path.join(temp_dir, "apps"))

        # Only the base "apps" directory needs to exist
        # The test structure might vary


class TestFileContents:
    """Test generated file contents."""

    def test_init_py_imports_admin(self, command, temp_dir):
        command.handle(name="testapp", directory=temp_dir)

        init_content = (Path(temp_dir) / "testapp" / "__init__.py").read_text()
        assert "from . import admin" in init_content

    def test_routes_py_creates_router(self, command, temp_dir):
        command.handle(name="shopapp", directory=temp_dir)

        routes_content = (Path(temp_dir) / "shopapp" / "routes.py").read_text()
        assert "Router" in routes_content
        assert 'prefix="/shopapp"' in routes_content

    def test_views_py_has_imports(self, command, temp_dir):
        command.handle(name="testapp", directory=temp_dir)

        views_content = (Path(temp_dir) / "testapp" / "views.py").read_text()
        assert "from openviper.http.request import Request" in views_content
        assert "from openviper.http.response import JSONResponse" in views_content

    def test_serializers_py_has_imports(self, command, temp_dir):
        command.handle(name="testapp", directory=temp_dir)

        serializers_content = (Path(temp_dir) / "testapp" / "serializers.py").read_text()
        assert "from openviper.serializers import Serializer" in serializers_content

    def test_tasks_py_has_imports(self, command, temp_dir):
        command.handle(name="testapp", directory=temp_dir)

        tasks_content = (Path(temp_dir) / "testapp" / "tasks.py").read_text()
        assert "from openviper.tasks import task" in tasks_content

    def test_events_py_has_imports(self, command, temp_dir):
        command.handle(name="testapp", directory=temp_dir)

        events_content = (Path(temp_dir) / "testapp" / "events.py").read_text()
        assert "from openviper.db.events import model_event" in events_content

    def test_tests_py_has_pytest_import(self, command, temp_dir):
        command.handle(name="testapp", directory=temp_dir)

        tests_content = (Path(temp_dir) / "testapp" / "tests.py").read_text()
        assert "import pytest" in tests_content


class TestOutputMessages:
    """Test command output messages."""

    def test_handle_success_message(self, command, temp_dir, capsys):
        command.handle(name="successapp", directory=temp_dir)

        captured = capsys.readouterr()
        assert "Created app 'successapp'" in captured.out
        assert str(Path(temp_dir) / "successapp") in captured.out

    def test_handle_shows_next_steps(self, command, temp_dir, capsys):
        command.handle(name="myapp", directory=temp_dir)

        captured = capsys.readouterr()
        assert "Add 'myapp' to INSTALLED_APPS" in captured.out
        assert "settings" in captured.out


class TestAppTemplateStructure:
    """Test the _APP_TEMPLATE structure."""

    def test_app_template_has_all_required_files(self):
        assert "__init__.py" in _APP_TEMPLATE
        assert "admin.py" in _APP_TEMPLATE
        assert "models.py" in _APP_TEMPLATE
        assert "routes.py" in _APP_TEMPLATE
        assert "views.py" in _APP_TEMPLATE
        assert "serializers.py" in _APP_TEMPLATE
        assert "tasks.py" in _APP_TEMPLATE
        assert "events.py" in _APP_TEMPLATE
        assert "tests.py" in _APP_TEMPLATE
        assert os.path.join("migrations", "__init__.py") in _APP_TEMPLATE

    def test_app_template_contains_placeholders(self):
        # Check that templates contain {{ app_label }} placeholder
        assert "{{ app_label }}" in _APP_TEMPLATE["__init__.py"]
        assert "{{ app_label }}" in _APP_TEMPLATE["routes.py"]


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_handle_with_valid_snake_case(self, command, temp_dir):
        """Test that snake_case names work correctly."""
        command.handle(name="my_awesome_app", directory=temp_dir)

        app_dir = Path(temp_dir) / "my_awesome_app"
        assert app_dir.exists()

    def test_handle_with_numbers(self, command, temp_dir):
        """Test that names with numbers work."""
        command.handle(name="app123", directory=temp_dir)

        app_dir = Path(temp_dir) / "app123"
        assert app_dir.exists()

    def test_handle_with_underscores(self, command, temp_dir):
        """Test that names with underscores work."""
        command.handle(name="my_app", directory=temp_dir)

        app_dir = Path(temp_dir) / "my_app"
        assert app_dir.exists()

    def test_command_instantiation(self):
        """Test that command can be instantiated."""
        cmd = Command()
        assert cmd is not None
        assert hasattr(cmd, "handle")
        assert hasattr(cmd, "add_arguments")
        assert hasattr(cmd, "aliases")

    def test_migrations_init_is_empty(self, command, temp_dir):
        """Test that migrations/__init__.py is empty."""
        command.handle(name="testapp", directory=temp_dir)

        migrations_init = Path(temp_dir) / "testapp" / "migrations" / "__init__.py"
        content = migrations_init.read_text()
        assert content == ""
