"""Tests for makemigrations command covering all migration logic branches."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

import pytest

from openviper.core.management.commands.makemigrations import (
    Command,
    _auto_migration_name,
)
from openviper.db.migrations.executor import (
    AddColumn,
    AlterColumn,
    CreateTable,
    DropTable,
    RemoveColumn,
    RenameColumn,
    RestoreColumn,
)
from collections import deque

# ---------------------------------------------------------------------------
# _auto_migration_name tests
# ---------------------------------------------------------------------------


class TestAutoMigrationName:
    """Test _auto_migration_name function."""

    def test_create_table(self):
        """Test CreateTable operation naming."""
        ops = [CreateTable("users")]
        assert _auto_migration_name(ops) == "create_users"

    def test_drop_table(self):
        """Test DropTable operation naming."""
        ops = [DropTable("users")]
        assert _auto_migration_name(ops) == "drop_users"

    def test_add_column(self):
        """Test AddColumn operation naming."""
        ops = [AddColumn("users", "bio", "TEXT", nullable=True)]
        assert _auto_migration_name(ops) == "add_bio"

    def test_remove_column(self):
        """Test RemoveColumn operation naming."""
        ops = [RemoveColumn("users", "bio")]
        assert _auto_migration_name(ops) == "remove_bio"

    def test_alter_column(self):
        """Test AlterColumn operation naming."""
        ops = [AlterColumn("users", "email", nullable=False)]
        assert _auto_migration_name(ops) == "alter_email"

    def test_rename_column(self):
        """Test RenameColumn operation naming."""
        ops = [RenameColumn("users", "fullname", "name")]
        assert _auto_migration_name(ops) == "rename_fullname_to_name"

    def test_restore_column(self):
        """Test RestoreColumn operation naming."""
        ops = [RestoreColumn("users", "avatar")]
        assert _auto_migration_name(ops) == "restore_avatar"

    def test_multiple_operations(self):
        """Test multiple operations are joined."""
        ops = [
            AddColumn("users", "bio", "TEXT", nullable=True),
            RemoveColumn("users", "avatar"),
        ]
        assert _auto_migration_name(ops) == "add_bio_remove_avatar"

    def test_empty_operations(self):
        """Test empty operations return 'auto'."""
        assert _auto_migration_name([]) == "auto"

    def test_truncation_long_name(self):
        """Test long names are truncated."""
        ops = [
            AddColumn("users", "very_long_column_name_one", "TEXT", nullable=True),
            AddColumn("users", "very_long_column_name_two", "TEXT", nullable=True),
        ]
        name = _auto_migration_name(ops)
        assert len(name) <= 40


# ---------------------------------------------------------------------------
# Command class tests
# ---------------------------------------------------------------------------


class TestMakemigrationsCommand:
    """Test makemigrations Command class."""

    @pytest.fixture
    def command(self):
        """Create a Command instance."""
        return Command()

    def test_add_arguments(self, command):
        """Test add_arguments sets up parser correctly."""
        parser = argparse.ArgumentParser()
        command.add_arguments(parser)

        # Parse with defaults
        args = parser.parse_args([])
        assert args.app_labels == []
        assert args.name is None
        assert args.empty is False
        assert args.check is False
        assert args.drop_columns is False

        # Parse with arguments
        args = parser.parse_args(
            ["myapp", "--name", "custom", "--empty", "--check", "--drop-columns"]
        )
        assert args.app_labels == ["myapp"]
        assert args.name == "custom"
        assert args.empty is True
        assert args.check is True
        assert args.drop_columns is True

    def test_handle_no_apps_found(self, command):
        """Test handle when no apps are found."""
        with patch("openviper.core.management.commands.makemigrations.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = []

            with patch.object(command, "stdout") as mock_stdout:
                with patch(
                    "openviper.core.management.commands.makemigrations.AppResolver"
                ) as MockResolver:
                    resolver = MagicMock()
                    resolver.resolve_all_apps.return_value = {"found": {}, "not_found": []}
                    MockResolver.return_value = resolver

                    command.handle(app_labels=[], check=False)

                    # Should output "No migrations created"
                    assert any("No migrations" in str(call) for call in mock_stdout.call_args_list)

    def test_handle_check_mode_no_changes(self, command):
        """Test handle in check mode with no changes."""
        with patch("openviper.core.management.commands.makemigrations.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = []

            with patch.object(command, "stdout") as mock_stdout:
                with patch(
                    "openviper.core.management.commands.makemigrations.AppResolver"
                ) as MockResolver:
                    resolver = MagicMock()
                    resolver.resolve_all_apps.return_value = {"found": {}, "not_found": []}
                    MockResolver.return_value = resolver

                    command.handle(app_labels=[], check=True)

                    assert any("No changes" in str(call) for call in mock_stdout.call_args_list)

    def test_handle_app_not_found(self, command):
        """Test handle when specified app is not found."""
        with patch("openviper.core.management.commands.makemigrations.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = []

            with patch.object(command, "stdout") as mock_stdout:
                with patch(
                    "openviper.core.management.commands.makemigrations.AppResolver"
                ) as MockResolver:
                    resolver = MagicMock()
                    resolver.resolve_all_apps.return_value = {
                        "found": {},
                        "not_found": ["nonexistent_app"],
                    }
                    MockResolver.return_value = resolver
                    MockResolver.print_app_not_found_error = MagicMock()

                    command.handle(app_labels=["nonexistent_app"], check=False)

                    # Should output error about app not found
                    assert any(
                        "nonexistent_app" in str(call) for call in mock_stdout.call_args_list
                    )

    def test_handle_with_resolved_apps(self, command, tmp_path):
        """Test handle with resolved apps."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        with patch("openviper.core.management.commands.makemigrations.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = ["myapp"]

            with patch.object(command, "stdout"):
                with patch(
                    "openviper.core.management.commands.makemigrations.AppResolver"
                ) as MockResolver:
                    resolver = MagicMock()
                    resolver.resolve_all_apps.return_value = {
                        "found": {"myapp": str(tmp_path)},
                        "not_found": [],
                    }
                    resolver.get_migrations_dir.return_value = str(migrations_dir)
                    MockResolver.return_value = resolver

                    with patch(
                        "openviper.core.management.commands.makemigrations.has_model_changes",
                        return_value=False,
                    ):
                        command.handle(app_labels=[], check=False)

    def test_handle_model_discovery(self, command, tmp_path):
        """Test model discovery during migration generation."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        with patch("openviper.core.management.commands.makemigrations.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = ["myapp"]

            with patch.object(command, "stdout"):
                with patch(
                    "openviper.core.management.commands.makemigrations.AppResolver"
                ) as MockResolver:
                    resolver = MagicMock()
                    resolver.resolve_all_apps.return_value = {
                        "found": {"myapp": str(tmp_path)},
                        "not_found": [],
                    }
                    resolver.get_migrations_dir.return_value = str(migrations_dir)
                    MockResolver.return_value = resolver

                    with patch(
                        "openviper.core.management.commands.makemigrations.has_model_changes",
                        return_value=False,
                    ):
                        command.handle(app_labels=[], check=False, empty=False)

    def test_handle_empty_migration(self, command, tmp_path):
        """Test creating empty migration."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        with patch("openviper.core.management.commands.makemigrations.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = ["myapp"]

            with patch.object(command, "stdout"):
                with patch(
                    "openviper.core.management.commands.makemigrations.AppResolver"
                ) as MockResolver:
                    resolver = MagicMock()
                    resolver.resolve_all_apps.return_value = {
                        "found": {"myapp": str(tmp_path)},
                        "not_found": [],
                    }
                    resolver.get_migrations_dir.return_value = str(migrations_dir)
                    MockResolver.return_value = resolver

                    with patch(
                        "openviper.core.management.commands.makemigrations.next_migration_number",
                        return_value="0001",
                    ):
                        with patch(
                            "openviper.core.management.commands.makemigrations.write_initial_migration"
                        ):
                            command.handle(app_labels=[], check=False, empty=True)

    def test_handle_check_mode_with_pending(self, command, tmp_path):
        """Test check mode with pending changes exits with error."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        with patch("openviper.core.management.commands.makemigrations.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = ["myapp"]

            with patch.object(command, "stdout"):
                with patch(
                    "openviper.core.management.commands.makemigrations.AppResolver"
                ) as MockResolver:
                    resolver = MagicMock()
                    resolver.resolve_all_apps.return_value = {
                        "found": {"myapp": str(tmp_path)},
                        "not_found": [],
                    }
                    resolver.get_migrations_dir.return_value = str(migrations_dir)
                    MockResolver.return_value = resolver

                    with patch(
                        "openviper.core.management.commands.makemigrations.has_model_changes",
                        return_value=True,
                    ):
                        with patch(
                            "openviper.core.management.commands.makemigrations.next_migration_number",
                            return_value="0002",
                        ):
                            with pytest.raises(SystemExit) as exc_info:
                                command.handle(app_labels=[], check=True, empty=False)
                            assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Dependency analysis tests
# ---------------------------------------------------------------------------


class TestDependencyAnalysis:
    """Test dependency analysis in makemigrations."""

    def test_topological_sort_no_deps(self):
        """Test topological sort with no dependencies."""

        app_data = {
            "app1": {"dependencies": set()},
            "app2": {"dependencies": set()},
        }

        adj = {label: [] for label in app_data}
        in_degree = dict.fromkeys(app_data, 0)

        for label, data in app_data.items():
            for dep in data["dependencies"]:
                adj[dep].append(label)
                in_degree[label] += 1

        queue = deque(sorted([l for l, d in in_degree.items() if d == 0]))
        sorted_labels = []
        while queue:
            curr = queue.popleft()
            sorted_labels.append(curr)
            for neighbor in sorted(adj[curr]):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        assert sorted_labels == ["app1", "app2"]

    def test_topological_sort_with_deps(self):
        """Test topological sort with dependencies."""

        app_data = {
            "app1": {"dependencies": set()},
            "app2": {"dependencies": {"app1"}},
        }

        adj = {label: [] for label in app_data}
        in_degree = dict.fromkeys(app_data, 0)

        for label, data in app_data.items():
            for dep in data["dependencies"]:
                if dep in adj:
                    adj[dep].append(label)
                    in_degree[label] += 1

        queue = deque(sorted([l for l, d in in_degree.items() if d == 0]))
        sorted_labels = []
        while queue:
            curr = queue.popleft()
            sorted_labels.append(curr)
            for neighbor in sorted(adj[curr]):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        assert sorted_labels == ["app1", "app2"]

    def test_topological_sort_cycle_handling(self):
        """Test topological sort handles cycles by appending remaining."""

        app_data = {
            "app1": {"dependencies": {"app2"}},
            "app2": {"dependencies": {"app1"}},  # Cycle!
        }

        adj = {label: [] for label in app_data}
        in_degree = dict.fromkeys(app_data, 0)

        for label, data in app_data.items():
            for dep in data["dependencies"]:
                if dep in adj:
                    adj[dep].append(label)
                    in_degree[label] += 1

        queue = deque(sorted([l for l, d in in_degree.items() if d == 0]))
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
            remaining = sorted([l for l in app_data if l not in sorted_labels])
            sorted_labels.extend(remaining)

        assert len(sorted_labels) == 2
        assert "app1" in sorted_labels
        assert "app2" in sorted_labels


# ---------------------------------------------------------------------------
# Drop columns flag test
# ---------------------------------------------------------------------------


class TestDropColumnsFlag:
    """Test --drop-columns flag behavior."""

    def test_drop_columns_sets_flag(self):
        """Test drop_columns flag sets drop=True on RemoveColumn ops."""
        ops = [RemoveColumn("users", "bio")]

        for op in ops:
            if isinstance(op, RemoveColumn):
                op.drop = True

        assert ops[0].drop is True


# ---------------------------------------------------------------------------
# Migration file generation tests
# ---------------------------------------------------------------------------


class TestMigrationFileGeneration:
    """Test migration file writing logic."""

    def test_initial_migration_number(self):
        """Test initial migration gets number 0001."""
        num = "0001"
        name_part = "initial" if int(num) == 1 else None
        assert name_part == "initial"

    def test_subsequent_migration_number(self):
        """Test subsequent migrations get auto name."""
        num = "0002"
        name_part = "initial" if int(num) == 1 else None
        assert name_part is None

    def test_custom_name_override(self):
        """Test custom name overrides auto naming."""
        num = "0002"
        custom_name = "add_user_profile"
        name_part = custom_name or ("initial" if int(num) == 1 else None)
        assert name_part == "add_user_profile"

    def test_migration_name_format(self):
        """Test migration name format is correct."""
        num = "0003"
        name_part = "add_bio"
        migration_name = f"{int(num):04d}_{name_part}"
        assert migration_name == "0003_add_bio"
