from io import StringIO
from unittest.mock import patch

import pytest

from openviper.core.management.base import BaseCommand, CommandError


class MockCommand(BaseCommand):
    help = "Test command"

    def add_arguments(self, parser):
        parser.add_argument("--name", default="world")

    def handle(self, *args, **options):
        self.stdout(f"Hello {options['name']}")
        return "success"


class ErrorCommand(BaseCommand):
    def handle(self, *args, **options):
        raise CommandError("Fail", returncode=2)


def test_command_error():
    exc = CommandError("testing", returncode=5)
    assert str(exc) == "testing"
    assert exc.returncode == 5


def test_base_command_stdout_stderr():
    cmd = BaseCommand()
    with patch("sys.stdout", new=StringIO()) as fake_out:
        cmd.stdout("test message")
        assert fake_out.getvalue() == "test message\n"

    with patch("sys.stderr", new=StringIO()) as fake_err:
        cmd.stderr("error message")
        assert fake_err.getvalue() == "error message\n"


def test_base_command_styles():
    cmd = BaseCommand()
    assert "\033[32m" in cmd.style_success("ok")
    assert "\033[33m" in cmd.style_warning("warn")
    assert "\033[31m" in cmd.style_error("err")
    assert "\033[36m" in cmd.style_notice("note")
    assert "\033[1m" in cmd.style_bold("bold")
    assert "\033[2m" in cmd.style_dim("dim")


def test_base_command_parser():
    cmd = MockCommand()
    parser = cmd.create_parser("prog", "sub")
    assert parser.prog == "prog sub"
    assert parser.description == "Test command"


def test_base_command_print_help():
    cmd = MockCommand()
    with patch("sys.stdout", new=StringIO()) as fake_out:
        cmd.print_help("prog", "sub")
        assert "Test command" in fake_out.getvalue()
        assert "--name" in fake_out.getvalue()


def test_base_command_execute_success():
    cmd = MockCommand()
    with patch("sys.stdout", new=StringIO()) as fake_out:
        result = cmd.execute(name="tester")
        assert result == "success"
        assert "Hello tester" in fake_out.getvalue()


def test_base_command_execute_error():
    cmd = ErrorCommand()
    with patch("sys.stderr", new=StringIO()) as fake_err, patch("sys.exit") as mock_exit:
        cmd.execute()
        assert "CommandError: Fail" in fake_err.getvalue()
        mock_exit.assert_called_once_with(2)


def test_base_command_run_from_argv():
    cmd = MockCommand()
    with patch("sys.stdout", new=StringIO()) as fake_out:
        cmd.run_from_argv(["prog", "sub", "--name", "argv_user"])
        assert "Hello argv_user" in fake_out.getvalue()


def test_base_command_handle_not_implemented():
    cmd = BaseCommand()
    with pytest.raises(NotImplementedError):
        cmd.handle()
