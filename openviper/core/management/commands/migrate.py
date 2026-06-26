"""migrate management command.

Applies pending schema changes by diffing JSON schema files against
the live database.  Stateless and idempotent.
"""

from __future__ import annotations

import argparse
import os

from openviper.core.management.base import BaseCommand, NoModelsModule
from openviper.core.management.utils import (
    import_models_module,
    report_app_not_found,
    resolve_installed_apps,
    run_async_command,
)
from openviper.db.models import check_primary_keys
from openviper.db.schemas.sync import SchemaSync


class Command(BaseCommand):
    """Apply pending database schema changes from JSON schema files."""

    help = "Apply pending database schema changes from JSON schema files."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "app_label",
            nargs="?",
            help="Only sync this app (optional)",
        )
        parser.add_argument(
            "--database",
            default="default",
            help="Database alias to sync (default: default)",
        )
        parser.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            default=False,
            help="Show detailed operation output",
        )

    def handle(self, **options: object) -> None:  # type: ignore[override]
        app_label = options.get("app_label")
        database = str(options.get("database", "default"))
        verbose = bool(options.get("verbose", False))

        resolver, resolved_apps = resolve_installed_apps()

        if app_label:
            app_path, found = resolver.resolve_app(app_label)
            if not found:
                report_app_not_found(self, app_label)
                return

        for app_name, app_path in resolved_apps.items():
            try:
                import_models_module(app_name, app_path)
            except NoModelsModule:
                continue

        check_primary_keys()

        if verbose and resolved_apps:
            self.stdout(f"\n{self.style_notice('App Locations:')}\n")
            for app_name, app_path in sorted(resolved_apps.items()):
                rel_path = os.path.relpath(app_path, os.getcwd())
                self.stdout(f"  {self.style_success('✓')} {app_name} -> {rel_path}")
            self.stdout("")

        async def run() -> list[str]:
            sync = SchemaSync(
                resolved_apps=resolved_apps if isinstance(resolved_apps, dict) else None
            )
            return await sync.sync(
                target_app=app_label,
                verbose=verbose,
                database=database,
            )

        run_async_command(run())

        self.stdout(self.style_success("Schema sync complete."))
