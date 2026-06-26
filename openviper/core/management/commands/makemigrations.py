"""makemigrations management command.

Generates or updates JSON schema files from model introspection.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import orjson

from openviper.conf import settings
from openviper.core.app_resolver import AppResolver
from openviper.core.management.base import BaseCommand, NoModelsModule
from openviper.core.management.utils import (
    discover_models_in_module,
    import_models_module,
    report_app_not_found,
)
from openviper.db.models import ModelMeta, check_primary_keys
from openviper.db.schemas.detect import apply_change_metadata, detect_changes
from openviper.db.schemas.json_reader import read_all_json_schemas, read_all_raw_schemas
from openviper.db.schemas.json_writer import delete_json_schema, write_json_schema


class Command(BaseCommand):
    """Generate or update JSON schema files for model changes."""

    help = "Generate or update JSON schema files for model changes."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "app_labels",
            nargs="*",
            help="One or more app labels to generate schemas for (default: all)",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="Exit non-zero if schema changes are needed (no files written)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force type changes that would normally be rejected",
        )

    def handle(self, **options: object) -> None:  # type: ignore[override]
        app_labels = options.get("app_labels") or []
        check_only = bool(options.get("check", False))
        force = bool(options.get("force", False))

        installed: list[str] = getattr(settings, "INSTALLED_APPS", [])

        resolver = AppResolver()

        targets = list(app_labels) or [app for app in installed if not app.startswith("openviper.")]

        resolved = resolver.resolve_all_apps(targets, include_builtin=bool(app_labels))
        resolved_apps: dict[str, str] = resolved.get("found", {})
        not_found_apps: list[str] = resolved.get("not_found", [])

        if app_labels and not_found_apps:
            for app_name in not_found_apps:
                report_app_not_found(self, app_name)
            if not resolved_apps:
                return

        if resolved_apps:
            self.stdout(f"\n{self.style_notice('Detecting changes...')}\n")
            self.stdout(self.style_success("Found apps:"))
            for app_name, app_path in sorted(resolved_apps.items()):
                rel_path = os.path.relpath(app_path, os.getcwd())
                self.stdout(f"  {self.style_success('✓')} {app_name} -> {rel_path}")
            self.stdout("")

        if not resolved_apps:
            if check_only:
                self.stdout(self.style_success("No changes detected."))
            else:
                self.stdout(self.style_notice("No schemas created."))
            return

        all_installed = resolver.resolve_all_apps(
            installed,
            include_builtin=True,
        )
        all_apps: dict[str, str] = all_installed.get("found", {})
        for app_name, app_path in all_apps.items():
            try:
                import_models_module(app_name, app_path)
            except NoModelsModule:
                continue

        app_data: dict[str, dict[str, object]] = {}
        for app_name, app_path in resolved_apps.items():
            app_module_label = app_name.split(".")[-1]
            schemas_dir = self.get_schemas_dir(resolver, app_name)

            model_classes: list[type] = []
            try:
                mod = import_models_module(app_name, app_path)
            except NoModelsModule:
                mod = None
            if mod is not None:
                model_classes.extend(discover_models_in_module(mod))

            for cls in ModelMeta.registry.values():
                if (
                    getattr(cls, "_app_name", None) == app_module_label
                    and getattr(cls, "_is_auto_created", False)
                    and cls not in model_classes
                ):
                    model_classes.append(cls)

            app_data[app_module_label] = {
                "name": app_name,
                "path": app_path,
                "schemas_dir": schemas_dir,
                "model_classes": model_classes,
            }

        check_primary_keys()

        created: list[str] = []
        updated: list[str] = []
        deleted: list[str] = []
        pending: list[str] = []

        for app_module in sorted(app_data.keys()):
            data = app_data[app_module]
            schemas_dir = str(data["schemas_dir"])
            model_classes = list(data["model_classes"])  # type: ignore[arg-type]

            json_state = read_all_json_schemas(schemas_dir)
            raw_schemas = read_all_raw_schemas(schemas_dir)
            report = detect_changes(model_classes, json_state, app_module, force=force)

            if check_only:
                if report["created"] or report["updated"] or report["deleted"]:
                    self.stdout(self.style_warning(f"  Pending changes for '{app_module}'."))
                    pending.append(app_module)
                else:
                    self.stdout(self.style_notice(f"  No changes detected for '{app_module}'."))
                continue

            for model_cls in report["created"]:
                path = write_json_schema(schemas_dir, model_cls, app_module)
                if not path:
                    self.stdout(
                        self.style_notice(f"  Skipped {model_cls.__name__} (unmanaged)")
                    )
                    continue
                created.append(f"{app_module}/{model_cls.__name__}")
                self.stdout(
                    self.style_success(f"  Created {app_module}/schemas/{model_cls.__name__}.json")
                )

            for model_cls, changes in report["updated"]:
                existing = raw_schemas.get(model_cls._table_name)
                path = write_json_schema(
                    schemas_dir,
                    model_cls,
                    app_module,
                    existing_schema=existing,
                )
                if not path:
                    self.stdout(
                        self.style_notice(f"  Skipped {model_cls.__name__} (unmanaged)")
                    )
                    continue
                if changes:
                    schema_path = Path(path)
                    schema = orjson.loads(schema_path.read_bytes())
                    schema = apply_change_metadata(schema, changes)
                    schema_path.write_bytes(orjson.dumps(schema, option=orjson.OPT_INDENT_2))
                updated.append(f"{app_module}/{model_cls.__name__}")
                self.stdout(
                    self.style_success(f"  Updated {app_module}/schemas/{model_cls.__name__}.json")
                )

            for table_name in report["deleted"]:
                model_name = self.find_model_name_from_table(table_name, raw_schemas)
                if model_name:
                    delete_json_schema(schemas_dir, model_name)
                    deleted.append(f"{app_module}/{model_name}")
                    self.stdout(
                        self.style_warning(f"  Deleted {app_module}/schemas/{model_name}.json")
                    )

        if check_only:
            if pending:
                self.stdout(f"\n{self.style_warning('Changes detected.')}\n")
                sys.exit(1)
            else:
                self.stdout(f"\n{self.style_success('No changes detected.')}\n")
        else:
            total = len(created) + len(updated) + len(deleted)
            if total:
                parts: list[str] = []
                if created:
                    parts.append(f"{len(created)} created")
                if updated:
                    parts.append(f"{len(updated)} updated")
                if deleted:
                    parts.append(f"{len(deleted)} deleted")
                self.stdout(f"\n{self.style_success(f'Schemas: {", ".join(parts)}.')}\n")
            else:
                self.stdout(f"\n{self.style_notice('No schemas changed.')}\n")

    def get_schemas_dir(self, resolver: AppResolver, app_name: str) -> str:
        """Get or create the schemas directory for an app."""
        app_path, found = resolver.resolve_app(app_name)
        if not found or app_path is None:
            return os.path.join(os.getcwd(), "schemas")
        schemas_dir = os.path.join(app_path, "schemas")
        if not os.path.exists(schemas_dir):
            os.makedirs(schemas_dir)
        return schemas_dir

    def find_model_name_from_table(
        self,
        table_name: str,
        raw_schemas: dict[str, dict[str, object]],
    ) -> str | None:
        """Find the model name (file stem) from a table name."""
        schema = raw_schemas.get(table_name)
        if schema is None:
            return None
        model_name = schema.get("model")
        if isinstance(model_name, str):
            return model_name
        return None
