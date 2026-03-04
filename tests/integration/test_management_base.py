"""Integration tests for openviper.core.management.base and __init__."""

from __future__ import annotations

import sys
from io import StringIO

import pytest

from openviper.core.management.base import BaseCommand, CommandError

# ---------------------------------------------------------------------------
# CommandError
# ---------------------------------------------------------------------------


class TestCommandError:
    def test_default_returncode(self):
        err = CommandError("something went wrong")
        assert err.returncode == 1

    def test_custom_returncode(self):
        err = CommandError("failed", returncode=2)
        assert err.returncode == 2

    def test_message(self):
        err = CommandError("test message")
        assert str(err) == "test message"

    def test_is_exception(self):
        err = CommandError("err")
        assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# BaseCommand output methods
# ---------------------------------------------------------------------------


class ConcreteCommand(BaseCommand):
    help = "Test command"

    def handle(self, *args, **options):
        return options.get("value", "default")


class TestBaseCommandOutput:
    def test_stdout_writes_to_sys_stdout(self, capsys):
        cmd = ConcreteCommand()
        cmd.stdout("hello world")
        captured = capsys.readouterr()
        assert "hello world" in captured.out

    def test_stdout_custom_ending(self, capsys):
        cmd = ConcreteCommand()
        cmd.stdout("hi", ending="")
        captured = capsys.readouterr()
        assert captured.out == "hi"

    def test_stderr_writes_to_sys_stderr(self, capsys):
        cmd = ConcreteCommand()
        cmd.stderr("error occurred")
        captured = capsys.readouterr()
        assert "error occurred" in captured.err

    def test_style_success_green(self):
        cmd = ConcreteCommand()
        result = cmd.style_success("done")
        assert "\033[32m" in result
        assert "done" in result

    def test_style_warning_yellow(self):
        cmd = ConcreteCommand()
        result = cmd.style_warning("caution")
        assert "\033[33m" in result

    def test_style_error_red(self):
        cmd = ConcreteCommand()
        result = cmd.style_error("fail")
        assert "\033[31m" in result

    def test_style_notice_cyan(self):
        cmd = ConcreteCommand()
        result = cmd.style_notice("note")
        assert "\033[36m" in result

    def test_style_bold(self):
        cmd = ConcreteCommand()
        result = cmd.style_bold("bold text")
        assert "\033[1m" in result

    def test_style_dim(self):
        cmd = ConcreteCommand()
        result = cmd.style_dim("dim text")
        assert "\033[2m" in result


# ---------------------------------------------------------------------------
# BaseCommand argument parsing
# ---------------------------------------------------------------------------


class TestBaseCommandArgParsing:
    def test_create_parser_returns_argparser(self):
        cmd = ConcreteCommand()
        parser = cmd.create_parser("viperctl.py", "testcmd")
        assert parser is not None

    def test_create_parser_sets_prog(self):
        cmd = ConcreteCommand()
        parser = cmd.create_parser("viperctl.py", "mycommand")
        assert "mycommand" in parser.prog

    def test_create_parser_stores_parser(self):
        cmd = ConcreteCommand()
        parser = cmd.create_parser("viperctl.py", "testcmd")
        assert cmd._parser is parser

    def test_print_help_works(self, capsys):
        cmd = ConcreteCommand()
        cmd.print_help("viperctl.py", "testcmd")
        out = capsys.readouterr().out
        assert len(out) > 0

    def test_add_arguments_can_be_overridden(self):
        class ArgedCommand(BaseCommand):
            def add_arguments(self, parser):
                parser.add_argument("--name", default="world")

            def handle(self, **options):
                return options["name"]

        cmd = ArgedCommand()
        parser = cmd.create_parser("viperctl.py", "hello")
        opts = vars(parser.parse_args(["--name", "Alice"]))
        assert opts["name"] == "Alice"

    def test_run_from_argv_parses_and_calls_handle(self, capsys):
        class HelloCommand(BaseCommand):
            def add_arguments(self, parser):
                parser.add_argument("--greet", default="world")

            def handle(self, **options):
                self.stdout(f"Hello, {options['greet']}!")

        cmd = HelloCommand()
        cmd.run_from_argv(["viperctl.py", "hello", "--greet", "Alice"])
        captured = capsys.readouterr()
        assert "Hello, Alice!" in captured.out


# ---------------------------------------------------------------------------
# BaseCommand.execute
# ---------------------------------------------------------------------------


class TestBaseCommandExecute:
    def test_execute_returns_handle_output(self):
        class ReturnCommand(BaseCommand):
            def handle(self, *args, **options):
                return "success"

        cmd = ReturnCommand()
        result = cmd.execute()
        assert result == "success"

    def test_execute_command_error_exits(self):
        class FailCommand(BaseCommand):
            def handle(self, *args, **options):
                raise CommandError("fail", returncode=42)

        cmd = FailCommand()
        with pytest.raises(SystemExit) as exc_info:
            cmd.execute()
        assert exc_info.value.code == 42

    def test_execute_command_error_writes_to_stderr(self, capsys):
        class FailCommand(BaseCommand):
            def handle(self, *args, **options):
                raise CommandError("something broke")

        cmd = FailCommand()
        with pytest.raises(SystemExit):
            cmd.execute()
        err = capsys.readouterr().err
        assert "something broke" in err


# ---------------------------------------------------------------------------
# BaseCommand.handle raises NotImplementedError
# ---------------------------------------------------------------------------


class TestBaseCommandHandleAbstract:
    def test_handle_raises_not_implemented(self):
        cmd = BaseCommand()
        with pytest.raises(NotImplementedError):
            cmd.handle()


# ---------------------------------------------------------------------------
# management dispatcher
# ---------------------------------------------------------------------------


class TestManagementDispatcher:
    def test_find_builtin_migrate_command(self):
        from openviper.core.management import _find_command

        cmd = _find_command("migrate")
        assert cmd is not None

    def test_find_builtin_createsuperuser(self):
        from openviper.core.management import _find_command

        cmd = _find_command("createsuperuser")
        assert cmd is not None

    def test_find_unknown_command_raises(self):
        from openviper.core.management import _find_command

        with pytest.raises(CommandError):
            _find_command("nonexistent_command_xyz")

    def test_list_commands_returns_list(self):
        from openviper.core.management import _list_commands

        commands = _list_commands()
        assert isinstance(commands, list)
        assert len(commands) > 0

    def test_list_commands_includes_migrate(self):
        from openviper.core.management import _list_commands

        commands = _list_commands()
        assert "migrate" in commands or "makemigrations" in commands

    def test_execute_from_command_line_help_exits(self):
        from openviper.core.management import execute_from_command_line

        with pytest.raises(SystemExit) as exc_info:
            execute_from_command_line(["viperctl.py", "help"])
        assert exc_info.value.code == 0

    def test_execute_from_command_line_no_args_shows_help(self):
        from openviper.core.management import execute_from_command_line

        with pytest.raises(SystemExit) as exc_info:
            execute_from_command_line(["viperctl.py"])
        assert exc_info.value.code == 0

    def test_execute_from_command_line_unknown_exits_nonzero(self, capsys):
        from openviper.core.management import execute_from_command_line

        with pytest.raises(SystemExit) as exc_info:
            execute_from_command_line(["viperctl.py", "no_such_command_xyz"])
        assert exc_info.value.code != 0

    def test_execute_from_command_line_dash_h_exits_0(self):
        from openviper.core.management import execute_from_command_line

        with pytest.raises(SystemExit) as exc_info:
            execute_from_command_line(["viperctl.py", "-h"])
        assert exc_info.value.code == 0
