"""Unit tests for test management command."""

import sys
from unittest.mock import Mock, patch

import pytest

from openviper.core.management.commands.test import Command


@pytest.fixture
def command():
    """Create a Command instance."""
    return Command()


class TestTestCommand:
    """Test the test command."""

    def test_help_attribute(self, command):
        assert "Run the project test suite" in command.help
        assert "pytest" in command.help

    def test_has_test_attribute_false(self, command):
        """Test that __test__ is False to prevent pytest collection."""
        assert Command.__test__ is False

    def test_add_arguments(self, command):
        parser = Mock()
        parser.add_argument = Mock()

        command.add_arguments(parser)

        # Should add test_labels, -v, --failfast, --keepdb
        assert parser.add_argument.call_count >= 4


class TestHandleBasic:
    """Test basic handle functionality."""

    @patch("subprocess.run")
    def test_handle_runs_pytest(self, mock_run, command):
        mock_run.return_value = Mock(returncode=0)

        with pytest.raises(SystemExit):
            command.handle(test_labels=[], verbose=0, failfast=False, keepdb=False)

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert sys.executable in call_args
        assert "-m" in call_args
        assert "pytest" in call_args

    @patch("subprocess.run")
    def test_handle_default_runs_tests_directory(self, mock_run, command):
        mock_run.return_value = Mock(returncode=0)

        with pytest.raises(SystemExit):
            command.handle(test_labels=[], verbose=0, failfast=False, keepdb=False)

        call_args = mock_run.call_args[0][0]
        assert "tests/" in call_args


class TestVerbosity:
    """Test verbosity options."""

    @patch("subprocess.run")
    def test_handle_verbose_flag(self, mock_run, command):
        mock_run.return_value = Mock(returncode=0)

        with pytest.raises(SystemExit):
            command.handle(test_labels=[], verbose=1, failfast=False, keepdb=False)

        call_args = mock_run.call_args[0][0]
        assert "-v" in call_args

    @patch("subprocess.run")
    def test_handle_multiple_verbose_flags(self, mock_run, command):
        mock_run.return_value = Mock(returncode=0)

        with pytest.raises(SystemExit):
            command.handle(test_labels=[], verbose=2, failfast=False, keepdb=False)

        call_args = mock_run.call_args[0][0]
        assert "-vv" in call_args


class TestFailfast:
    """Test failfast option."""

    @patch("subprocess.run")
    def test_handle_failfast_flag(self, mock_run, command):
        mock_run.return_value = Mock(returncode=0)

        with pytest.raises(SystemExit):
            command.handle(test_labels=[], verbose=0, failfast=True, keepdb=False)

        call_args = mock_run.call_args[0][0]
        assert "-x" in call_args


class TestTestLabels:
    """Test test labels processing."""

    @patch("subprocess.run")
    def test_handle_with_test_labels(self, mock_run, command):
        mock_run.return_value = Mock(returncode=0)

        with pytest.raises(SystemExit):
            command.handle(
                test_labels=["tests/unit/", "tests/integration/"],
                verbose=0,
                failfast=False,
                keepdb=False,
            )

        call_args = mock_run.call_args[0][0]
        assert "tests/unit/" in call_args
        assert "tests/integration/" in call_args

    @patch("subprocess.run")
    def test_handle_processes_test_labels_with_colon(self, mock_run, command):
        """Test that .py: is converted to .py::"""
        mock_run.return_value = Mock(returncode=0)

        with pytest.raises(SystemExit):
            command.handle(
                test_labels=["tests/test_file.py:test_func"],
                verbose=0,
                failfast=False,
                keepdb=False,
            )

        call_args = mock_run.call_args[0][0]
        assert "tests/test_file.py::test_func" in call_args


class TestReturnCode:
    """Test return code handling."""

    @patch("subprocess.run")
    def test_handle_exits_with_pytest_returncode(self, mock_run, command):
        mock_run.return_value = Mock(returncode=42)

        with pytest.raises(SystemExit) as exc_info:
            command.handle(test_labels=[], verbose=0, failfast=False, keepdb=False)

        assert exc_info.value.code == 42

    @patch("subprocess.run")
    def test_handle_exits_zero_on_success(self, mock_run, command):
        mock_run.return_value = Mock(returncode=0)

        with pytest.raises(SystemExit) as exc_info:
            command.handle(test_labels=[], verbose=0, failfast=False, keepdb=False)

        assert exc_info.value.code == 0


class TestEnvironment:
    """Test environment variable setting."""

    @patch("subprocess.run")
    def test_handle_sets_openviper_env(self, mock_run, command):
        mock_run.return_value = Mock(returncode=0)

        with pytest.raises(SystemExit):
            command.handle(test_labels=[], verbose=0, failfast=False, keepdb=False)

        call_kwargs = mock_run.call_args[1]
        assert "env" in call_kwargs
        assert call_kwargs["env"]["OPENVIPER_ENV"] == "testing"


class TestOutput:
    """Test command output."""

    @patch("subprocess.run")
    def test_handle_prints_command(self, mock_run, command, capsys):
        mock_run.return_value = Mock(returncode=0)

        with pytest.raises(SystemExit):
            command.handle(test_labels=[], verbose=0, failfast=False, keepdb=False)

        captured = capsys.readouterr()
        assert "Running:" in captured.out
        assert "pytest" in captured.out
