"""create_command management command — scaffold a new management command."""

from __future__ import annotations

import argparse
import os

from openviper.core.management.base import BaseCommand, CommandError

_COMMAND_TEMPLATE = '''"""{command_name} management command."""

from __future__ import annotations

import argparse

from openviper.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Describe your command here."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        # Add your arguments here
        # parser.add_argument("name", help="Description")
        pass

    def handle(self, **options):  # type: ignore[override]
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

    def handle(self, **options):  # type: ignore[override]
        command_name: str = options["command_name"]
        app_name: str = options["app_name"]
        base_dir = options.get("directory") or os.getcwd()

        if not command_name.isidentifier():
            raise CommandError(f"'{command_name}' is not a valid Python identifier.")

        commands_dir = os.path.join(base_dir, app_name, "management", "commands")
        os.makedirs(commands_dir, exist_ok=True)

        # Ensure __init__.py files exist
        for pkg_dir in [
            os.path.join(base_dir, app_name, "management"),
            commands_dir,
        ]:
            init = os.path.join(pkg_dir, "__init__.py")
            if not os.path.exists(init):
                with open(init, "w", encoding="utf-8"):
                    pass  # create empty __init__.py

        file_path = os.path.join(commands_dir, f"{command_name}.py")
        if os.path.exists(file_path):
            raise CommandError(f"Command file '{file_path}' already exists.")

        with open(file_path, "w", encoding="utf-8") as fh:
            fh.write(_COMMAND_TEMPLATE.format(command_name=command_name))

        self.stdout(self.style_success(f"Created command '{command_name}' at {file_path}"))
