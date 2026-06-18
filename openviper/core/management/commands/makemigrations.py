"""makemigrations management command."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from collections import deque
from pathlib import Path

from openviper.conf import settings
from openviper.core.app_resolver import AppResolver
from openviper.core.management.base import BaseCommand
from openviper.core.management.utils import discover_models_in_module, report_app_not_found
from openviper.db.fields import ForeignKey
from openviper.db.migrations.executor import (  # noqa: N814
    AddColumn,
    AlterColumn,
    CreateTable,
    DropTable,
    RemoveColumn,
    RenameColumn,
    RestoreColumn,
)
from openviper.db.migrations.writer import (
    diff_states,
    has_model_changes,
    model_state_snapshot,
    next_migration_number,
    read_migrated_state,
    write_initial_migration,
    write_migration,
)
from openviper.db.models import ModelMeta, check_primary_keys

MAX_NAME_LENGTH = 40


def auto_migration_name(ops: list) -> str:
    """Derive a meaningful migration name from a list of operations.

    Produces names like ``add_bio_remove_profile_image``,
    ``alter_users_email_add_avatar``, ``create_post``, etc.
    """

    parts: list[str] = []
    for op in ops:
        if isinstance(op, CreateTable):
            parts.append(f"create_{op.table_name}")
        elif isinstance(op, DropTable):
            parts.append(f"drop_{op.table_name}")
        elif isinstance(op, AddColumn):
            parts.append(f"add_{op.column_name}")
        elif isinstance(op, RemoveColumn):
            parts.append(f"remove_{op.column_name}")
        elif isinstance(op, AlterColumn):
            parts.append(f"alter_{op.table_name}_{op.column_name}")
        elif isinstance(op, RenameColumn):
            parts.append(f"rename_{op.old_name}_to_{op.new_name}")
        elif isinstance(op, RestoreColumn):
            parts.append(f"restore_{op.column_name}")

    if not parts:
        return "auto"

    # Deduplicate consecutive identical name parts to prevent redundant
    # repetition when multiple operations target the same column.
    deduped: list[str] = []
    for part in parts:
        if not deduped or deduped[-1] != part:
            deduped.append(part)

    name = "_".join(deduped)
    if len(name) > MAX_NAME_LENGTH:
        name = name[:MAX_NAME_LENGTH].rsplit("_", 1)[0]
    return name


class Command(BaseCommand):
    help = "Auto-generate migration files for model changes."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "app_labels",
            nargs="*",
            help="One or more app labels to generate migrations for (default: all)",
        )
        parser.add_argument("--name", "-n", default=None, help="Custom migration name")
        parser.add_argument(
            "--empty",
            action="store_true",
            help="Create an empty migration file",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="Exit non-zero if migrations are needed (no files written)",
        )
        parser.add_argument(
            "--drop-columns",
            action="store_true",
            help="Permanently DROP removed columns instead of renaming them (data loss!)",
        )

    def handle(self, **options) -> None:  # type: ignore[override]

        app_labels = options.get("app_labels") or []
        custom_name = options.get("name")
        check_only = options.get("check", False)
        empty = options.get("empty", False)
        drop_columns = options.get("drop_columns", False)

        installed = getattr(settings, "INSTALLED_APPS", [])

        resolver = AppResolver()

        targets = app_labels or [app for app in installed if not app.startswith("openviper.")]

        resolved = resolver.resolve_all_apps(targets, include_builtin=bool(app_labels))
        resolved_apps = resolved.get("found", {})
        not_found_apps = resolved.get("not_found", [])

        if app_labels and not_found_apps:
            for app_name in not_found_apps:
                report_app_not_found(self, app_name)
            if not resolved_apps:
                return

        if resolved_apps:
            self.stdout(f"\n{self.style_notice('Detecting changes...')}\n")
            self.stdout(self.style_success("Found apps:"))
            for app_name, app_path in sorted(
                resolved_apps.items() if isinstance(resolved_apps, dict) else []
            ):
                rel_path = os.path.relpath(app_path, os.getcwd())
                self.stdout(f"  {self.style_success('✓')} {app_name} → {rel_path}")
            self.stdout("")

        if not resolved_apps:
            if check_only:
                self.stdout(self.style_success("No changes detected."))
            else:
                self.stdout(self.style_notice("No migrations created."))
            return

        created: list[str] = []
        pending_changes = []  # Track pending changes in check mode

        app_data = {}
        for app_name, app_path in resolved_apps.items():
            app_module_label = app_name.split(".")[-1]
            migrations_dir = resolver.get_migrations_dir(app_name)
            if migrations_dir is None:
                continue

            model_classes: list[type] = []
            if not empty:
                try:
                    mod = importlib.import_module(f"{app_name}.models")
                    model_classes.extend(discover_models_in_module(mod))
                except (ImportError, ModuleNotFoundError):
                    try:
                        sys.path.insert(0, app_path)
                        qualified_name = f"{app_name}.models"
                        mod = importlib.import_module(qualified_name)
                        model_classes.extend(discover_models_in_module(mod))
                    except (ImportError, ModuleNotFoundError):
                        pass
                    finally:
                        if app_path in sys.path:
                            sys.path.remove(app_path)

            # ManyToManyField without explicit 'through' models are registered
            # in ModelMeta.registry during module import and must be included.
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
                "migrations_dir": migrations_dir,
                "model_classes": model_classes,
                "dependencies": set(),
            }

        for app_label, data in app_data.items():
            for cls in data["model_classes"]:
                for field in cls._fields.values():
                    if isinstance(field, ForeignKey):
                        target = field.resolve_target()
                        if (
                            target
                            and hasattr(target, "_app_name")
                            and target._app_name != app_label
                        ) and target._app_name in app_data:
                            data["dependencies"].add(target._app_name)

        adj = {label: [] for label in app_data}
        in_degree = dict.fromkeys(app_data, 0)
        for label, data in app_data.items():
            for dep in data["dependencies"]:
                adj[dep].append(label)
                in_degree[label] += 1

        queue = deque(sorted([label for label, degree in in_degree.items() if degree == 0]))
        sorted_labels = []
        while queue:
            curr = queue.popleft()
            sorted_labels.append(curr)
            for neighbor in sorted(adj[curr]):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Cycles still produce migrations despite ambiguous order.
        if len(sorted_labels) < len(app_data):
            remaining = sorted([label for label in app_data if label not in sorted_labels])
            sorted_labels.extend(remaining)

        # Primary key misconfiguration produces silent data corruption;
        # catching it before file writes avoids orphaned migration files.
        check_primary_keys()

        created = []
        pending_changes = []

        for app_module in sorted_labels:
            data = app_data[app_module]
            app_name = data["name"]
            migrations_dir = data["migrations_dir"]
            model_classes = data["model_classes"]

            if not empty and not has_model_changes(model_classes, migrations_dir):
                self.stdout(self.style_notice(f"  ⊘ {app_module}: No changes detected"))
                continue

            num = next_migration_number(migrations_dir)
            name_part = custom_name or ("initial" if int(num) == 1 else None)

            if check_only:
                if name_part is None:
                    name_part = "auto"
                migration_name = f"{int(num):04d}_{name_part}"
                self.stdout(self.style_warning(f"  Pending changes detected for '{app_module}'."))
                pending_changes.append(f"{app_module}/{migration_name}")
                continue

            deps = []

            # Each app must chain off its own previous migration to preserve order.
            if int(num) > 1:
                previous_num = int(num) - 1
                existing_in_app = [
                    f.stem for f in Path(migrations_dir).glob("*.py") if not f.stem.startswith("_")
                ]
                for name in sorted(existing_in_app):
                    if name.startswith(f"{previous_num:04d}_"):
                        deps.append((app_module, name))
                        break

            # Cross-app ForeignKeys impose ordering constraints between apps.
            if not empty:
                for cls in model_classes:
                    for field in cls._fields.values():
                        if isinstance(field, ForeignKey):
                            target = field.resolve_target()
                            if (
                                target
                                and hasattr(target, "_app_name")
                                and target._app_name != app_module
                            ):
                                target_app_label = target._app_name
                                target_migrations_dir = (
                                    resolver.get_migrations_dir(target_app_label) or ""
                                )
                                if os.path.isdir(target_migrations_dir):
                                    existing = [
                                        f.stem
                                        for f in Path(target_migrations_dir).glob("*.py")
                                        if not f.stem.startswith("_")
                                    ]
                                    if existing:
                                        deps.append((target_app_label, sorted(existing)[-1]))
            deps = sorted(set(deps))

            if empty or int(num) == 1:
                if name_part is None:
                    name_part = "initial"
                migration_name = f"{int(num):04d}_{name_part}"
                write_initial_migration(
                    app_module,
                    model_classes,
                    migrations_dir,
                    migration_name=migration_name,
                    dependencies=deps,
                )
            else:
                current_state = model_state_snapshot(model_classes)
                existing_state = read_migrated_state(migrations_dir)
                ops = diff_states(current_state, existing_state)
                if not ops:
                    self.stdout(self.style_notice(f"  ⊘ {app_module}: No changes detected"))
                    continue
                if drop_columns:
                    for op in ops:
                        if isinstance(op, RemoveColumn):
                            op.drop = True
                if name_part is None:
                    name_part = auto_migration_name(ops)
                migration_name = f"{int(num):04d}_{name_part}"
                write_migration(
                    app_module,
                    ops,
                    migrations_dir,
                    migration_name=migration_name,
                    dependencies=deps,
                )

            created.append(f"{app_module}/{migration_name}")
            self.stdout(
                self.style_success(f"  Created {app_module}/migrations/{migration_name}.py")
            )

        if check_only:
            if created or pending_changes:
                self.stdout(f"\n{self.style_warning('Changes detected.')}\n")
                sys.exit(1)
            else:
                self.stdout(f"\n{self.style_success('No changes detected.')}\n")
        elif not created:
            self.stdout(f"\n{self.style_notice('No migrations created.')}\n")
        else:
            self.stdout(f"\n{self.style_success(f'Created {len(created)} migration(s).')}\n")
