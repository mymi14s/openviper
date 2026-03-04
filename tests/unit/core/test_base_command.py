import argparse
from unittest.mock import patch

import pytest

from openviper.core.management.base import BaseCommand, CommandError


class DummyCommand(BaseCommand):
    help = "Dummy cmd"

    def add_arguments(self, parser):
        parser.add_argument("--foo", default="bar")

    def handle(self, *args, **options):
        if options.get("foo") == "crash":
            raise CommandError("Crashing!", returncode=2)
        return "success!"


def test_command_error():
    err = CommandError("test", returncode=5)
    assert err.returncode == 5
    assert str(err) == "test"


def test_base_command_styling():
    cmd = DummyCommand()
    assert "\033[32m" in cmd.style_success("msg")
    assert "\033[33m" in cmd.style_warning("msg")
    assert "\033[31m" in cmd.style_error("msg")
    assert "\033[36m" in cmd.style_notice("msg")
    assert "\033[1m" in cmd.style_bold("msg")
    assert "\033[2m" in cmd.style_dim("msg")


def test_base_command_io(capsys):
    cmd = DummyCommand()
    cmd.stdout("Standard out message")
    cmd.stderr("Standard err message")

    captured = capsys.readouterr()
    assert "Standard out message" in captured.out
    assert "Standard err message" in captured.err


def test_base_command_print_help(capsys):
    cmd = DummyCommand()
    cmd.print_help("viperctl.py", "dummy")
    captured = capsys.readouterr()
    assert "viperctl.py dummy" in captured.out
    assert "Dummy cmd" in captured.out


def test_base_command_execute():
    cmd = DummyCommand()
    assert cmd.execute(foo="bar") == "success!"

    with pytest.raises(SystemExit) as exc, patch.object(cmd, "stderr") as mock_err:
        cmd.execute(foo="crash")
    assert exc.value.code == 2
    mock_err.assert_called_once()


def test_base_command_run_from_argv():
    cmd = DummyCommand()
    with patch.object(cmd, "execute") as mock_exec:
        cmd.run_from_argv(["viperctl.py", "dummy", "--foo", "baz"])
        mock_exec.assert_called_once_with(foo="baz")


def test_base_command_unimplemented_handle():
    class IncompleteCommand(BaseCommand):
        pass

    cmd = IncompleteCommand()
    with pytest.raises(NotImplementedError):
        cmd.handle()
