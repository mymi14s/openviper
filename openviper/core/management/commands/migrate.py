"""migrate management command."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from openviper.conf import settings
from openviper.core.app_resolver import AppResolver
from openviper.core.management.base import BaseCommand
from openviper.db.migrations.executor import MigrationExecutor


class Command(BaseCommand):
    help = "Apply pending database migrations."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "app_label",
            nargs="?",
            help="Only migrate this app (optional)",
        )
        parser.add_argument(
            "migration_name",
            nargs="?",
            help="Migrate to this specific migration (optional)",
        )
        parser.add_argument(
            "--fake",
            action="store_true",
            help="Mark migrations as applied without running SQL",
        )
        parser.add_argument(
            "--database",
            default="default",
            help="Database alias to migrate (default: default)",
        )

    def handle(self, **options):  # type: ignore[override]

        app_label = options.get("app_label")
        migration_name = options.get("migration_name")

        # Use enhanced logging only when stdout is a TTY (not in tests/pipes)
        use_verbose = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

        # Resolve app locations from INSTALLED_APPS
        resolver = AppResolver()
        installed_apps = getattr(settings, "INSTALLED_APPS", [])

        # If specific app requested, validate it exists
        if app_label:
            app_path, found = resolver.resolve_app(app_label)
            if not found:
                self.stdout(
                    self.style_error(
                        f"\nError: App '{app_label}' not found in project"
                        f" or settings.INSTALLED_APPS\n"
                    )
                )
                AppResolver.print_app_not_found_error(
                    app_label,
                    [
                        f"{app_label}/",
                        f"apps/{app_label}/",
                        f"src/{app_label}/",
                    ],
                )
                return

        # Resolve all apps
        resolved = resolver.resolve_all_apps(installed_apps)
        resolved_apps = resolved.get("found", {})

        if use_verbose and resolved_apps:
            # Show app locations in verbose mode
            print(f"\n{self.style_notice('App Locations:')}\n")
            for app_name, app_path in sorted(
                resolved_apps.items() if isinstance(resolved_apps, dict) else []
            ):
                rel_path = os.path.relpath(app_path, os.getcwd())
                print(f"  {self.style_success('✓')} {app_name} → {rel_path}")
            print()

        if not use_verbose:
            self.stdout("Running migrations…")

        async def run() -> list[str]:
            executor = MigrationExecutor(
                resolved_apps=resolved_apps if isinstance(resolved_apps, dict) else None
            )
            return await executor.migrate(
                target_app=app_label,
                target_name=migration_name,
                verbose=use_verbose,
            )

        applied = asyncio.run(run())

        if not applied:
            self.stdout(self.style_notice("  No migrations to apply."))
        elif not use_verbose:
            # Only print individual migrations if not in verbose mode
            for name in applied:
                self.stdout(self.style_success(f"  Applying {name}… OK"))

        self.stdout(self.style_success("Migrations complete."))
