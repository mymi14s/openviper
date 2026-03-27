"""Additional branch tests for makemigrations command.

These focus on the remaining untested control-flow in the command handler.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openviper.core.management.commands.makemigrations import Command
from openviper.db.migrations.executor import RemoveColumn

_REAL_IMPORT_MODULE = importlib.import_module


class TestMakemigrationsMoreBranches:
    @pytest.fixture
    def command(self) -> Command:
        return Command()

    def test_app_not_found_but_some_found_continues(self, command: Command, tmp_path: Path) -> None:
        app_dir = tmp_path / "app1"
        app_dir.mkdir()
        migrations_dir = app_dir / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        with (
            patch("openviper.core.management.commands.makemigrations.settings") as mock_settings,
            patch(
                "openviper.core.management.commands.makemigrations.AppResolver"
            ) as mock_resolver_cls,
            patch(
                "openviper.core.management.commands.makemigrations.next_migration_number",
                return_value="0001",
            ),
            patch(
                "openviper.core.management.commands.makemigrations.write_initial_migration"
            ) as mock_write,
            patch.object(command, "stdout") as mock_stdout,
        ):
            mock_settings.INSTALLED_APPS = ["app1", "missing"]
            resolver = MagicMock()
            resolver.resolve_all_apps.return_value = {
                "found": {"app1": str(app_dir)},
                "not_found": ["missing"],
            }
            resolver.get_migrations_dir.return_value = str(migrations_dir)
            mock_resolver_cls.return_value = resolver

            command.handle(app_labels=["app1", "missing"], check=False, empty=True)

        assert mock_write.call_count == 1
        assert any("missing" in str(c) for c in mock_stdout.call_args_list)

    def test_model_import_fallback_to_local_models_module_cleans_sys_path(
        self, command: Command, tmp_path: Path
    ) -> None:
        app_dir = tmp_path / "fallbackapp"
        app_dir.mkdir()
        migrations_dir = app_dir / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        dummy_base = type("Model", (), {})
        dummy_model = type("MyModel", (dummy_base,), {"_fields": {}})

        mod = types.ModuleType("models")
        mod.MyModel = dummy_model

        original_sys_path = list(sys.path)

        def import_side_effect(name: str):
            if name.endswith(".models"):
                raise ImportError("no package models")
            if name == "models":
                return mod
            return _REAL_IMPORT_MODULE(name)

        with (
            patch("openviper.core.management.commands.makemigrations.settings") as mock_settings,
            patch("openviper.core.management.commands.makemigrations.Model", dummy_base),
            patch(
                "openviper.core.management.commands.makemigrations.AppResolver"
            ) as mock_resolver_cls,
            patch(
                "openviper.core.management.commands.makemigrations.has_model_changes",
                return_value=False,
            ),
            patch.object(command, "stdout"),
        ):
            mock_settings.INSTALLED_APPS = ["fallbackapp"]
            resolver = MagicMock()
            resolver.resolve_all_apps.return_value = {
                "found": {"fallbackapp": str(app_dir)},
                "not_found": [],
            }
            resolver.get_migrations_dir.return_value = str(migrations_dir)
            mock_resolver_cls.return_value = resolver

            with patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                side_effect=import_side_effect,
            ):
                command.handle(app_labels=[], check=False, empty=False)

        assert list(sys.path) == original_sys_path

    def test_write_migration_includes_intra_and_inter_app_dependencies(
        self, command: Command, tmp_path: Path
    ) -> None:
        app1_dir = tmp_path / "app1"
        app2_dir = tmp_path / "app2"
        for d in (app1_dir, app2_dir):
            d.mkdir()
            (d / "migrations").mkdir()
            ((d / "migrations") / "__init__.py").write_text("")

        # previous migration in app1
        ((app1_dir / "migrations") / "0001_initial.py").write_text("# x")
        # latest migration in app2
        ((app2_dir / "migrations") / "0009_last.py").write_text("# x")

        dummy_base = type("Model", (), {})

        class FK:  # stub for isinstance checks
            def __init__(self, target):
                self._target = target

            def resolve_target(self):
                return self._target

        target_model = type("Target", (), {"_app_name": "app2"})
        model_with_fk = type(
            "M",
            (dummy_base,),
            {"_fields": {"fk": FK(target_model)}, "__module__": "x"},
        )

        def get_migrations_dir(name: str) -> str | None:
            if name == "app1":
                return str(app1_dir / "migrations")
            if name == "app2":
                return str(app2_dir / "migrations")
            return None

        ops = [RemoveColumn("t", "c")]

        with (
            patch("openviper.core.management.commands.makemigrations.settings") as mock_settings,
            patch("openviper.core.management.commands.makemigrations.Model", dummy_base),
            patch("openviper.core.management.commands.makemigrations.ForeignKey", FK),
            patch(
                "openviper.core.management.commands.makemigrations.AppResolver"
            ) as mock_resolver_cls,
            patch(
                "openviper.core.management.commands.makemigrations.has_model_changes",
                return_value=True,
            ),
            patch(
                "openviper.core.management.commands.makemigrations.next_migration_number",
                return_value="0002",
            ),
            patch("openviper.core.management.commands.makemigrations.model_state_snapshot"),
            patch("openviper.core.management.commands.makemigrations.read_migrated_state"),
            patch(
                "openviper.core.management.commands.makemigrations._diff_states", return_value=ops
            ),
            patch(
                "openviper.core.management.commands.makemigrations._auto_migration_name",
                return_value="auto",
            ),
            patch(
                "openviper.core.management.commands.makemigrations.write_migration"
            ) as mock_write_migration,
            patch.object(command, "stdout"),
        ):
            mock_settings.INSTALLED_APPS = ["app1", "app2"]
            resolver = MagicMock()
            resolver.resolve_all_apps.return_value = {
                "found": {"app1": str(app1_dir), "app2": str(app2_dir)},
                "not_found": [],
            }
            resolver.get_migrations_dir.side_effect = get_migrations_dir
            mock_resolver_cls.return_value = resolver

            def import_side_effect(name: str):
                if name in {"app1.models", "app2.models"}:
                    return types.ModuleType("x")
                return _REAL_IMPORT_MODULE(name)

            with patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[("M", model_with_fk)],
            ):
                with patch(
                    "openviper.core.management.commands.makemigrations.importlib.import_module",
                    side_effect=import_side_effect,
                ):
                    command.handle(app_labels=[], check=False, empty=False)

        deps_by_app = {
            c.args[0]: c.kwargs["dependencies"] for c in mock_write_migration.call_args_list
        }
        deps = deps_by_app["app1"]
        assert ("app1", "0001_initial") in deps
        assert ("app2", "0009_last") in deps

    def test_drop_columns_sets_remove_column_drop_true(
        self, command: Command, tmp_path: Path
    ) -> None:
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        migrations_dir = app_dir / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        op = RemoveColumn("t", "c")

        with (
            patch("openviper.core.management.commands.makemigrations.settings") as mock_settings,
            patch(
                "openviper.core.management.commands.makemigrations.AppResolver"
            ) as mock_resolver_cls,
            patch(
                "openviper.core.management.commands.makemigrations.has_model_changes",
                return_value=True,
            ),
            patch(
                "openviper.core.management.commands.makemigrations.next_migration_number",
                return_value="0002",
            ),
            patch("openviper.core.management.commands.makemigrations.model_state_snapshot"),
            patch("openviper.core.management.commands.makemigrations.read_migrated_state"),
            patch(
                "openviper.core.management.commands.makemigrations._diff_states", return_value=[op]
            ),
            patch(
                "openviper.core.management.commands.makemigrations.write_migration"
            ) as mock_write_migration,
            patch(
                "openviper.core.management.commands.makemigrations._auto_migration_name",
                return_value="auto",
            ),
            patch.object(command, "stdout"),
        ):
            mock_settings.INSTALLED_APPS = ["app"]
            resolver = MagicMock()
            resolver.resolve_all_apps.return_value = {
                "found": {"app": str(app_dir)},
                "not_found": [],
            }
            resolver.get_migrations_dir.return_value = str(migrations_dir)
            mock_resolver_cls.return_value = resolver

            with patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ):
                with patch(
                    "openviper.core.management.commands.makemigrations.importlib.import_module",
                    return_value=types.ModuleType("x"),
                ):
                    command.handle(app_labels=[], check=False, empty=False, drop_columns=True)

        called_op = mock_write_migration.call_args.args[1][0]
        assert isinstance(called_op, RemoveColumn)
        assert called_op.drop is True

    def test_diff_states_empty_skips_write(self, command: Command, tmp_path: Path) -> None:
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        migrations_dir = app_dir / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        with (
            patch("openviper.core.management.commands.makemigrations.settings") as mock_settings,
            patch(
                "openviper.core.management.commands.makemigrations.AppResolver"
            ) as mock_resolver_cls,
            patch(
                "openviper.core.management.commands.makemigrations.has_model_changes",
                return_value=True,
            ),
            patch(
                "openviper.core.management.commands.makemigrations.next_migration_number",
                return_value="0002",
            ),
            patch("openviper.core.management.commands.makemigrations.model_state_snapshot"),
            patch("openviper.core.management.commands.makemigrations.read_migrated_state"),
            patch(
                "openviper.core.management.commands.makemigrations._diff_states", return_value=[]
            ),
            patch(
                "openviper.core.management.commands.makemigrations.write_migration"
            ) as mock_write_migration,
            patch.object(command, "stdout") as mock_stdout,
        ):
            mock_settings.INSTALLED_APPS = ["app"]
            resolver = MagicMock()
            resolver.resolve_all_apps.return_value = {
                "found": {"app": str(app_dir)},
                "not_found": [],
            }
            resolver.get_migrations_dir.return_value = str(migrations_dir)
            mock_resolver_cls.return_value = resolver

            with patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ):
                with patch(
                    "openviper.core.management.commands.makemigrations.importlib.import_module",
                    return_value=types.ModuleType("x"),
                ):
                    command.handle(app_labels=[], check=False, empty=False)

        mock_write_migration.assert_not_called()
        assert any("No changes detected" in str(c) for c in mock_stdout.call_args_list)

    def test_check_only_with_resolved_apps_but_no_changes_exits_successfully(
        self, command: Command, tmp_path: Path
    ) -> None:
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        migrations_dir = app_dir / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        with (
            patch("openviper.core.management.commands.makemigrations.settings") as mock_settings,
            patch(
                "openviper.core.management.commands.makemigrations.AppResolver"
            ) as mock_resolver_cls,
            patch(
                "openviper.core.management.commands.makemigrations.has_model_changes",
                return_value=False,
            ),
            patch.object(command, "stdout") as mock_stdout,
        ):
            mock_settings.INSTALLED_APPS = ["app"]
            resolver = MagicMock()
            resolver.resolve_all_apps.return_value = {
                "found": {"app": str(app_dir)},
                "not_found": [],
            }
            resolver.get_migrations_dir.return_value = str(migrations_dir)
            mock_resolver_cls.return_value = resolver

            command.handle(app_labels=[], check=True, empty=False)

        assert any("No changes detected" in str(c) for c in mock_stdout.call_args_list)
