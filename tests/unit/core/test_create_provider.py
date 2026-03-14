"""Unit tests for create_provider management command."""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from openviper.core.management.base import CommandError
from openviper.core.management.commands.create_provider import (
    Command,
    _render,
    _to_class_name,
    _to_env_var,
)


@pytest.fixture
def command():
    """Create a Command instance."""
    return Command()


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


class TestHelperFunctions:
    """Test helper functions."""

    def test_to_class_name_snake_case(self):
        assert _to_class_name("my_provider") == "MyProviderProvider"

    def test_to_class_name_kebab_case(self):
        assert _to_class_name("my-provider") == "MyProviderProvider"

    def test_to_class_name_single_word(self):
        assert _to_class_name("openai") == "OpenaiProvider"

    def test_to_class_name_multiple_words(self):
        assert _to_class_name("my_custom_ai") == "MyCustomAiProvider"

    def test_to_env_var_snake_case(self):
        assert _to_env_var("my_provider") == "MY_PROVIDER_API_KEY"

    def test_to_env_var_kebab_case(self):
        assert _to_env_var("my-provider") == "MY_PROVIDER_API_KEY"

    def test_to_env_var_single_word(self):
        assert _to_env_var("openai") == "OPENAI_API_KEY"

    def test_render_simple_placeholder(self):
        template = "Hello {{ name }}"
        ctx = {"name": "World"}
        assert _render(template, ctx) == "Hello World"

    def test_render_multiple_placeholders(self):
        template = "{{ greeting }} {{ name }}!"
        ctx = {"greeting": "Hello", "name": "Alice"}
        assert _render(template, ctx) == "Hello Alice!"

    def test_render_no_placeholders(self):
        template = "No placeholders here"
        ctx = {}
        assert _render(template, ctx) == "No placeholders here"


class TestCreateProviderCommand:
    """Test create_provider command basic functionality."""

    def test_help_attribute(self, command):
        assert "Scaffold a new custom AI provider" in command.help

    def test_add_arguments(self, command):
        parser = Mock()
        parser.add_argument = Mock()

        command.add_arguments(parser)

        # Should add name and --output-dir arguments
        assert parser.add_argument.call_count == 2

        calls = parser.add_argument.call_args_list
        assert any("name" in str(call) for call in calls)
        assert any("--output-dir" in str(call) for call in calls)


class TestProviderCreation:
    """Test provider package creation."""

    def test_handle_creates_provider_directory(self, command, temp_dir, capsys):
        command.handle(name="myprovider", output_dir=temp_dir)

        provider_dir = Path(temp_dir) / "myprovider"
        assert provider_dir.exists()
        assert provider_dir.is_dir()

        captured = capsys.readouterr()
        assert "Created provider package 'myprovider'" in captured.out

    def test_handle_creates_all_files(self, command, temp_dir):
        command.handle(name="testprovider", output_dir=temp_dir)

        provider_dir = Path(temp_dir) / "testprovider"

        # Check all files exist
        assert (provider_dir / "__init__.py").exists()
        assert (provider_dir / "provider.py").exists()
        assert (provider_dir / "README.md").exists()

        tests_dir = provider_dir / "tests"
        assert tests_dir.exists()
        assert (tests_dir / "__init__.py").exists()
        assert (tests_dir / "test_testprovider.py").exists()

    def test_handle_creates_tests_directory(self, command, temp_dir):
        command.handle(name="myprovider", output_dir=temp_dir)

        tests_dir = Path(temp_dir) / "myprovider" / "tests"
        assert tests_dir.exists()
        assert tests_dir.is_dir()

    def test_handle_provider_py_has_correct_class(self, command, temp_dir):
        command.handle(name="custom_ai", output_dir=temp_dir)

        provider_file = Path(temp_dir) / "custom_ai" / "provider.py"
        content = provider_file.read_text()

        assert "class CustomAiProvider(AIProvider)" in content
        assert 'name = "custom_ai"' in content

    def test_handle_init_py_exports_provider(self, command, temp_dir):
        command.handle(name="myprovider", output_dir=temp_dir)

        init_file = Path(temp_dir) / "myprovider" / "__init__.py"
        content = init_file.read_text()

        assert "from .provider import MyproviderProvider, get_providers" in content
        assert "__all__" in content


class TestValidation:
    """Test input validation."""

    def test_handle_invalid_name_raises_error(self, command, temp_dir):
        with pytest.raises(CommandError) as exc_info:
            command.handle(name="123invalid", output_dir=temp_dir)

        assert "not a valid Python identifier" in str(exc_info.value)

    def test_handle_existing_directory_raises_error(self, command, temp_dir):
        # Create the directory first
        provider_dir = Path(temp_dir) / "existing"
        provider_dir.mkdir()

        with pytest.raises(CommandError) as exc_info:
            command.handle(name="existing", output_dir=temp_dir)

        assert "already exists" in str(exc_info.value)

    def test_handle_normalizes_hyphens(self, command, temp_dir):
        """Test that hyphens are converted to underscores."""
        command.handle(name="my-provider", output_dir=temp_dir)

        provider_dir = Path(temp_dir) / "my_provider"
        assert provider_dir.exists()


class TestProviderFileContent:
    """Test generated provider file content."""

    def test_handle_provider_has_generate_method(self, command, temp_dir):
        command.handle(name="testprovider", output_dir=temp_dir)

        provider_file = Path(temp_dir) / "testprovider" / "provider.py"
        content = provider_file.read_text()

        assert "async def generate" in content
        assert "async def stream" in content

    def test_handle_provider_has_env_var(self, command, temp_dir):
        command.handle(name="custom_ai", output_dir=temp_dir)

        provider_file = Path(temp_dir) / "custom_ai" / "provider.py"
        content = provider_file.read_text()

        assert "CUSTOM_AI_API_KEY" in content

    def test_handle_provider_has_docstring(self, command, temp_dir):
        command.handle(name="myprovider", output_dir=temp_dir)

        provider_file = Path(temp_dir) / "myprovider" / "provider.py"
        content = provider_file.read_text()

        assert '"""Myprovider provider.' in content or '"""Myprovider AI provider.' in content

    def test_handle_test_file_has_tests(self, command, temp_dir):
        command.handle(name="testprovider", output_dir=temp_dir)

        test_file = Path(temp_dir) / "testprovider" / "tests" / "test_testprovider.py"
        content = test_file.read_text()

        assert "def test_provider_name" in content
        assert "def test_supported_models" in content
        assert "async def test_generate" in content
        assert "async def test_stream" in content


class TestREADMEContent:
    """Test README.md content."""

    def test_handle_readme_has_installation(self, command, temp_dir):
        command.handle(name="myprovider", output_dir=temp_dir)

        readme_file = Path(temp_dir) / "myprovider" / "README.md"
        content = readme_file.read_text()

        assert "Installation" in content
        assert "pip install" in content

    def test_handle_readme_has_configuration(self, command, temp_dir):
        command.handle(name="myprovider", output_dir=temp_dir)

        readme_file = Path(temp_dir) / "myprovider" / "README.md"
        content = readme_file.read_text()

        assert "Configuration" in content
        assert "AI_PROVIDERS" in content
        assert "MYPROVIDER_API_KEY" in content

    def test_handle_readme_has_usage(self, command, temp_dir):
        command.handle(name="myprovider", output_dir=temp_dir)

        readme_file = Path(temp_dir) / "myprovider" / "README.md"
        content = readme_file.read_text()

        assert "Usage" in content
        assert "model_router" in content


class TestOutputMessages:
    """Test command output messages."""

    def test_handle_success_message_with_next_steps(self, command, temp_dir, capsys):
        command.handle(name="myprovider", output_dir=temp_dir)

        captured = capsys.readouterr()
        assert "Created provider package 'myprovider'" in captured.out
        assert "Next steps:" in captured.out
        assert "Implement generate()" in captured.out
        assert "MYPROVIDER_API_KEY" in captured.out
        assert "Run tests: pytest" in captured.out

    def test_handle_shows_file_path(self, command, temp_dir, capsys):
        command.handle(name="testprovider", output_dir=temp_dir)

        captured = capsys.readouterr()
        assert "testprovider/provider.py" in captured.out or "provider.py" in captured.out


class TestDirectoryOption:
    """Test --output-dir option."""

    def test_handle_uses_current_directory_by_default(self, command):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                command.handle(name="defaultprovider", output_dir=None)

                provider_dir = Path(tmpdir) / "defaultprovider"
                assert provider_dir.exists()
            finally:
                os.chdir(original_cwd)

    def test_handle_uses_custom_directory(self, command, temp_dir):
        command.handle(name="customprovider", output_dir=temp_dir)

        provider_dir = Path(temp_dir) / "customprovider"
        assert provider_dir.exists()


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_handle_with_underscores(self, command, temp_dir):
        command.handle(name="my_provider", output_dir=temp_dir)

        provider_dir = Path(temp_dir) / "my_provider"
        assert provider_dir.exists()

    def test_handle_single_letter_name(self, command, temp_dir):
        command.handle(name="x", output_dir=temp_dir)

        provider_dir = Path(temp_dir) / "x"
        assert provider_dir.exists()

        # Check class name
        provider_file = provider_dir / "provider.py"
        content = provider_file.read_text()
        assert "class XProvider(AIProvider)" in content

    def test_handle_long_name(self, command, temp_dir):
        long_name = "very_long_provider_name_with_multiple_words"
        command.handle(name=long_name, output_dir=temp_dir)

        provider_dir = Path(temp_dir) / long_name
        assert provider_dir.exists()

    def test_command_instantiation(self):
        """Test that command can be instantiated."""
        cmd = Command()
        assert cmd is not None
        assert hasattr(cmd, "handle")
        assert hasattr(cmd, "add_arguments")

    def test_tests_init_is_empty(self, command, temp_dir):
        command.handle(name="testprovider", output_dir=temp_dir)

        tests_init = Path(temp_dir) / "testprovider" / "tests" / "__init__.py"
        content = tests_init.read_text()
        assert content == ""
