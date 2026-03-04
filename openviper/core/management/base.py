"""Base management command class."""

from __future__ import annotations

import argparse
import sys
from typing import Any


class CommandError(Exception):
    """Raised by management commands to signal a non-zero exit."""

    def __init__(self, message: str, returncode: int = 1) -> None:
        super().__init__(message)
        self.returncode = returncode


class BaseCommand:
    """Abstract base for all OpenViper management commands.

    Subclass and implement :py:meth:`handle`.  Optionally override
    :py:meth:`add_arguments` to register argparse arguments.

    Example::

        from openviper.core.management.base import BaseCommand

        class Command(BaseCommand):
            help = "Print hello message"

            def add_arguments(self, parser):
                parser.add_argument("name", nargs="?", default="world")

            def handle(self, *args, **options):
                self.stdout(f"Hello, {options['name']}!")
    """

    help: str = ""
    requires_system_checks: bool = True

    def __init__(self) -> None:
        self._parser: argparse.ArgumentParser | None = None

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------

    def stdout(self, message: str, ending: str = "\n") -> None:
        sys.stdout.write(message + ending)
        sys.stdout.flush()

    def stderr(self, message: str, ending: str = "\n") -> None:
        sys.stderr.write(message + ending)
        sys.stderr.flush()

    def style_success(self, message: str) -> str:
        return f"\033[32m{message}\033[0m"

    def style_warning(self, message: str) -> str:
        return f"\033[33m{message}\033[0m"

    def style_error(self, message: str) -> str:
        return f"\033[31m{message}\033[0m"

    def style_notice(self, message: str) -> str:
        return f"\033[36m{message}\033[0m"

    def style_bold(self, message: str) -> str:
        return f"\033[1m{message}\033[22m"

    def style_dim(self, message: str) -> str:
        return f"\033[2m{message}\033[22m"

    # ------------------------------------------------------------------
    # Argument parsing
    # ------------------------------------------------------------------

    def create_parser(self, prog_name: str, subcommand: str) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog=f"{prog_name} {subcommand}",
            description=self.help or None,
        )
        self.add_arguments(parser)
        self._parser = parser
        return parser

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Override to add custom arguments."""

    def print_help(self, prog_name: str, subcommand: str) -> None:
        parser = self.create_parser(prog_name, subcommand)
        parser.print_help()

    # ------------------------------------------------------------------
    # Execution entry point
    # ------------------------------------------------------------------

    def execute(self, *args: Any, **options: Any) -> Any:
        try:
            output = self.handle(*args, **options)
        except CommandError as exc:
            self.stderr(self.style_error(f"CommandError: {exc}"))
            sys.exit(exc.returncode)
        return output

    def run_from_argv(self, argv: list[str]) -> None:
        """Parse *argv* and dispatch to :meth:`execute`."""
        parser = self.create_parser(argv[0], argv[1])
        options = vars(parser.parse_args(argv[2:]))
        self.execute(**options)

    def handle(self, *args: Any, **options: Any) -> Any:
        raise NotImplementedError("Subclasses must implement handle()")
