"""create_command management command - scaffold a new management command."""

from __future__ import annotations

import argparse
from pathlib import Path

from openviper.core.management.base import BaseCommand, CommandError
from openviper.core.management.utils import validate_identifier

COMMAND_TEMPLATE = '''"""{command_name} management command."""

from __future__ import annotations

import argparse

from openviper.core.management.base import BaseCommand

class Command(BaseCommand):
    help = "Describe your command here."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        # Add your arguments here
        # parser.add_argument("name", help="Description")
        pass

    def handle(self, **options: object) -> None:
        self.stdout(self.style_success("Command executed successfully."))
'''


class Command(BaseCommand):
    help = "Create a new management command file inside an app."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("command_name", help="Name of the new command (snake_case)")
        parser.add_argument(
            "app_name",
            help="App that will own this command",
        )
        parser.add_argument(
            "--directory",
            "-d",
            default=None,
            help="Base directory (default: current working directory)",
        )

    def handle(self, **options: object) -> None:
        command_name = str(options["command_name"])
        validate_identifier(command_name, "command name")
        app_name = str(options["app_name"])
        base_dir = Path(str(options.get("directory") or ".")).resolve()

        app_relative_path = Path(app_name)
        if app_relative_path.is_absolute() or ".." in app_relative_path.parts:
            raise CommandError(f"'{app_name}' is not a safe app path.")

        app_path = (base_dir / app_relative_path).resolve()
        if not app_path.is_relative_to(base_dir):
            raise CommandError(f"'{app_name}' resolves outside the base directory.")

        commands_dir = app_path / "management" / "commands"
        commands_dir.mkdir(parents=True, exist_ok=True)

        for pkg_dir in (
            app_path / "management",
            commands_dir,
        ):
            init = pkg_dir / "__init__.py"
            if not init.exists():
                init.touch()

        file_path = commands_dir / f"{command_name}.py"
        if file_path.exists():
            raise CommandError(f"Command file '{file_path}' already exists.")

        with file_path.open("w", encoding="utf-8") as fh:
            fh.write(COMMAND_TEMPLATE.format(command_name=command_name))

        self.stdout(self.style_success(f"Created command '{command_name}' at {file_path}"))
