import argparse
import os
from unittest.mock import MagicMock, mock_open, patch

import pytest

from openviper.core.management.base import CommandError
from openviper.core.management.commands.create_provider import (
    Command,
    _render,
    _to_class_name,
    _to_env_var,
)


def test_to_class_name():
    assert _to_class_name("my_provider") == "MyProviderProvider"
    assert _to_class_name("my-provider") == "MyProviderProvider"
    assert _to_class_name("provider") == "ProviderProvider"


def test_to_env_var():
    assert _to_env_var("my_provider") == "MY_PROVIDER_API_KEY"
    assert _to_env_var("my-provider") == "MY_PROVIDER_API_KEY"


def test_render():
    template = "Hello {{ name }}!"
    ctx = {"name": "World"}
    assert _render(template, ctx) == "Hello World!"


def test_add_arguments():

    cmd = Command()
    parser = argparse.ArgumentParser()
    cmd.add_arguments(parser)
    # Check if 'name' and '--output-dir' are added
    actions = [a.dest for a in parser._actions]
    assert "name" in actions
    assert "output_dir" in actions


class TestCreateProviderCommand:
    def test_handle_invalid_identifier(self):
        cmd = Command()
        with pytest.raises(CommandError, match="not a valid Python identifier"):
            cmd.handle(name="123-bad", output_dir=None)

    @patch("os.path.exists")
    def test_handle_directory_exists(self, mock_exists):
        mock_exists.return_value = True
        cmd = Command()
        with pytest.raises(CommandError, match="already exists"):
            cmd.handle(name="my_provider", output_dir=None)

    @patch("os.makedirs")
    @patch("os.path.exists")
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.getcwd")
    def test_handle_success(self, mock_getcwd, mock_file, mock_exists, mock_makedirs):
        mock_getcwd.return_value = "/tmp"
        mock_exists.return_value = False

        cmd = Command()
        # Mock stdout to avoid printing to console during tests
        cmd.stdout = MagicMock()

        cmd.handle(name="test_provider", output_dir="/fake/dir")

        # Verify directory creation
        expected_pkg_dir = os.path.join("/fake/dir", "test_provider")
        expected_tests_dir = os.path.join(expected_pkg_dir, "tests")
        mock_makedirs.assert_called_once_with(expected_tests_dir, exist_ok=True)

        # Verify files written
        # 5 files: __init__.py, provider.py, tests/__init__.py,
        # tests/test_test_provider.py, README.md
        assert mock_file.call_count == 5

        # Verify some content (checking if _render was called implicitly)
        written_paths = [args[0] for args, _ in mock_file.call_args_list]
        assert any("provider.py" in p for p in written_paths)
        assert any("README.md" in p for p in written_paths)

    @patch("os.makedirs")
    @patch("os.path.exists")
    @patch("builtins.open", new_callable=mock_open)
    def test_handle_default_output_dir(self, mock_file, mock_exists, mock_makedirs):
        mock_exists.return_value = False

        cmd = Command()
        cmd.stdout = MagicMock()

        with patch("os.getcwd", return_value="/cwd"):
            cmd.handle(name="my_prov", output_dir=None)

        mock_makedirs.assert_called_once()
        # Check if it used os.getcwd()
        args, _ = mock_makedirs.call_args
        assert "/cwd/my_prov" in args[0]
