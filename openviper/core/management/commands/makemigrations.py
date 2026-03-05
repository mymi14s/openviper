"""makemigrations management command."""

from __future__ import annotations

import argparse
import importlib
import inspect
import os
import sys
from collections import deque
from pathlib import Path

from openviper.conf import settings
from openviper.core.app_resolver import AppResolver
from openviper.core.management.base import BaseCommand
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
from openviper.db.migrations.executor import (
    RemoveColumn as _RemoveColumn,
)
from openviper.db.migrations.writer import (
    _diff_states,
    has_model_changes,
    model_state_snapshot,
    next_migration_number,
    read_migrated_state,
    write_initial_migration,
    write_migration,
)
from openviper.db.models import Model

# Maximum length for the auto-generated descriptive part of a migration name
_MAX_NAME_LENGTH = 40


def _auto_migration_name(ops: list) -> str:
    """Derive a meaningful migration name from a list of operations.
    from openviper.db.migrations.executor import (
            AddColumn,
            AlterColumn,
            CreateTable,
            DropTable,
            RemoveColumn,
            RenameColumn,
            RestoreColumn,
        )
    from openviper.core.app_resolver import AppResolver


        Produces names like ``add_bio_remove_profile_image``,
        ``alter_email_add_avatar``, ``create_post``, etc.
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
            parts.append(f"alter_{op.column_name}")
        elif isinstance(op, RenameColumn):
            parts.append(f"rename_{op.old_name}_to_{op.new_name}")
        elif isinstance(op, RestoreColumn):
            parts.append(f"restore_{op.column_name}")

    if not parts:
        return "auto"

    name = "_".join(parts)
    # Truncate if too long, keeping it readable
    if len(name) > _MAX_NAME_LENGTH:
        name = name[:_MAX_NAME_LENGTH].rsplit("_", 1)[0]
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

    def handle(self, **options):  # type: ignore[override]

        app_labels = options.get("app_labels") or []
        custom_name = options.get("name")
        check_only = options.get("check", False)
        empty = options.get("empty", False)
        drop_columns = options.get("drop_columns", False)

        installed = getattr(settings, "INSTALLED_APPS", [])

        # Resolve app locations
        resolver = AppResolver()

        # Determine target apps
        targets = app_labels or [app for app in installed if not app.startswith("openviper.")]

        # Try to resolve all target apps
        resolved = resolver.resolve_all_apps(targets, include_builtin=bool(app_labels))
        resolved_apps = resolved.get("found", {})
        not_found_apps = resolved.get("not_found", [])

        # If specific app labels were requested and some not found, report error
        if app_labels and not_found_apps:
            for app_name in not_found_apps:
                self.stdout(
                    self.style_error(
                        f"\nError: App '{app_name}' does not exist or could not be found."
                    )
                )
                AppResolver.print_app_not_found_error(
                    app_name,
                    [
                        f"{app_name}/",
                        f"apps/{app_name}/",
                        f"src/{app_name}/",
                    ],
                )
            if not resolved_apps:
                return
        elif not_found_apps:
            # Auto-detected apps that weren't found — just skip silently
            pass

        # Show app locations if we found any
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

        # Discovery Phase
        app_data = {}
        for app_name, app_path in resolved_apps.items():
            app_module_label = app_name.split(".")[-1]
            migrations_dir = resolver.get_migrations_dir(app_name)
            if migrations_dir is None:
                continue

            # Discover Model subclasses
            model_classes: list[type] = []
            if not empty:
                try:
                    mod = importlib.import_module(f"{app_name}.models")
                    for _name, obj in inspect.getmembers(mod, inspect.isclass):
                        if (
                            issubclass(obj, Model)
                            and obj is not Model
                            and obj.__module__ == mod.__name__
                        ):
                            meta = getattr(obj, "Meta", None)
                            if meta and getattr(meta, "abstract", False):
                                continue
                            model_classes.append(obj)
                except (ImportError, ModuleNotFoundError):
                    try:
                        sys.path.insert(0, app_path)
                        mod = importlib.import_module("models")
                        for _name, obj in inspect.getmembers(mod, inspect.isclass):
                            if (
                                issubclass(obj, Model)
                                and obj is not Model
                                and obj.__module__ == mod.__name__
                            ):
                                meta = getattr(obj, "Meta", None)
                                if meta and getattr(meta, "abstract", False):
                                    continue
                                model_classes.append(obj)
                    except (ImportError, ModuleNotFoundError):
                        pass
                    finally:
                        if app_path in sys.path:
                            sys.path.remove(app_path)

            app_data[app_module_label] = {
                "name": app_name,
                "path": app_path,
                "migrations_dir": migrations_dir,
                "model_classes": model_classes,
                "dependencies": set(),
            }

        # Dependency Analysis Phase
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

        # Topological Sort Phase
        adj = {label: [] for label in app_data}
        in_degree = dict.fromkeys(app_data, 0)
        for label, data in app_data.items():
            for dep in data["dependencies"]:
                adj[dep].append(label)
                in_degree[label] += 1

        queue = deque(sorted([_l for _l, d in in_degree.items() if d == 0]))
        sorted_labels = []
        while queue:
            curr = queue.popleft()
            sorted_labels.append(curr)
            for neighbor in sorted(adj[curr]):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Handle remaining (cycles)
        if len(sorted_labels) < len(app_data):
            remaining = sorted([_l for _l in app_data if _l not in sorted_labels])
            sorted_labels.extend(remaining)

        created = []
        pending_changes = []

        # Generation Phase
        for app_module in sorted_labels:
            data = app_data[app_module]
            app_name = data["name"]
            migrations_dir = data["migrations_dir"]
            model_classes = data["model_classes"]

            # Skip if models haven't changed since last migration
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

            # Calculate actual dependencies for the migration file
            deps = []
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
                ops = _diff_states(current_state, existing_state)
                if not ops:
                    self.stdout(self.style_notice(f"  ⊘ {app_module}: No changes detected"))
                    continue
                if drop_columns:

                    for op in ops:
                        if isinstance(op, _RemoveColumn):
                            op.drop = True
                if name_part is None:
                    name_part = _auto_migration_name(ops)
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
