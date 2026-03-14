"""collectstatic management command."""

from __future__ import annotations

import argparse

from openviper.conf import settings
from openviper.core.management.base import BaseCommand
from openviper.staticfiles.handlers import collect_static


class Command(BaseCommand):
    help = "Copy static files from all STATICFILES_DIRS into STATIC_ROOT."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--no-input",
            action="store_true",
            default=False,
            help="Do not prompt for confirmation",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear STATIC_ROOT before collecting",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be collected without copying",
        )

    def handle(self, **options):  # type: ignore[override]

        static_root = getattr(settings, "STATIC_ROOT", "static")
        source_dirs = getattr(settings, "STATICFILES_DIRS", ["static"])
        clear = options.get("clear", False)
        no_input = options.get("no_input", False)
        dry_run = options.get("dry_run", False)

        if dry_run:
            self.stdout(
                self.style_notice(
                    f"Would collect static files from installed apps"
                    f" and {source_dirs} → {static_root}"
                )
            )
            return

        if not no_input:
            answer = (
                input(
                    f"This will copy files from installed apps and {source_dirs} "
                    f"to '{static_root}'. Continue? [yes/no]: "
                )
                .strip()
                .lower()
            )
            if answer not in ("yes", "y"):
                self.stdout("Aborted.")
                return

        count = collect_static(source_dirs, static_root, clear=clear)
        self.stdout(self.style_success(f"Collected {count} static file(s) to '{static_root}'."))
