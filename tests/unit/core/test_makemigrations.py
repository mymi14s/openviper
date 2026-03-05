"""Unit tests for the makemigrations management command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openviper.core.management.commands.makemigrations import Command, _auto_migration_name
from openviper.db.migrations.executor import (
    AddColumn,
    AlterColumn,
    CreateTable,
    DropTable,
    RemoveColumn,
    RenameColumn,
    RestoreColumn,
)

# ---------------------------------------------------------------------------
# _auto_migration_name tests
# ---------------------------------------------------------------------------


class TestAutoMigrationName:
    def test_empty_ops_returns_auto(self):
        assert _auto_migration_name([]) == "auto"

    def test_create_table(self):
        op = CreateTable(table_name="users")
        assert _auto_migration_name([op]) == "create_users"

    def test_drop_table(self):
        op = DropTable(table_name="old_table")
        assert _auto_migration_name([op]) == "drop_old_table"

    def test_add_column(self):
        op = AddColumn(table_name="users", column_name="email", column_type="TEXT")
        assert _auto_migration_name([op]) == "add_email"

    def test_remove_column(self):
        op = RemoveColumn(table_name="users", column_name="avatar")
        assert _auto_migration_name([op]) == "remove_avatar"

    def test_alter_column(self):
        op = AlterColumn(table_name="users", column_name="bio")
        assert _auto_migration_name([op]) == "alter_bio"

    def test_rename_column(self):
        op = RenameColumn(table_name="users", old_name="fname", new_name="first_name")
        assert _auto_migration_name([op]) == "rename_fname_to_first_name"

    def test_restore_column(self):
        op = RestoreColumn(table_name="users", column_name="deleted_at")
        assert _auto_migration_name([op]) == "restore_deleted_at"

    def test_multiple_ops_joined(self):
        ops = [
            AddColumn(table_name="t", column_name="bio", column_type="TEXT"),
            RemoveColumn(table_name="t", column_name="old_field"),
        ]
        result = _auto_migration_name(ops)
        assert "add_bio" in result
        assert "remove_old_field" in result

    def test_long_name_truncated_to_max(self):
        from openviper.core.management.commands.makemigrations import _MAX_NAME_LENGTH

        op = AddColumn(table_name="t", column_name="x" * 50, column_type="TEXT")
        result = _auto_migration_name([op])
        assert len(result) <= _MAX_NAME_LENGTH

    def test_unknown_op_type_skipped(self):
        """Operations we do not handle just produce no parts -> 'auto'."""
        unknown = MagicMock(spec=[])  # does not match any isinstance check
        result = _auto_migration_name([unknown])
        assert result == "auto"


# ---------------------------------------------------------------------------
# add_arguments
# ---------------------------------------------------------------------------


def test_add_arguments_parses_all_flags():
    import argparse

    cmd = Command()
    parser = argparse.ArgumentParser()
    cmd.add_arguments(parser)

    args = parser.parse_args(["myapp", "--name", "myname", "--empty", "--check", "--drop-columns"])
    assert args.app_labels == ["myapp"]
    assert args.name == "myname"
    assert args.empty is True
    assert args.check is True
    assert args.drop_columns is True


def test_add_arguments_defaults():
    import argparse

    cmd = Command()
    parser = argparse.ArgumentParser()
    cmd.add_arguments(parser)

    args = parser.parse_args([])
    assert args.app_labels == []
    assert args.name is None
    assert args.empty is False
    assert args.check is False
    assert args.drop_columns is False


# ---------------------------------------------------------------------------
# handle() – helpers
# ---------------------------------------------------------------------------


def _make_resolver(resolved_apps=None, not_found=None, migrations_dir="/fake/migrations"):
    resolver = MagicMock()
    resolver.resolve_all_apps.return_value = {
        "found": resolved_apps if resolved_apps is not None else {},
        "not_found": not_found if not_found is not None else [],
    }
    resolver.get_migrations_dir.return_value = migrations_dir
    return resolver


# ---------------------------------------------------------------------------
# handle() – no apps / empty state
# ---------------------------------------------------------------------------


class TestHandleNoApps:
    @patch("openviper.core.management.commands.makemigrations.AppResolver")
    @patch("openviper.core.management.commands.makemigrations.settings")
    def test_no_installed_apps_no_migrations_created(self, mock_settings, MockResolver):
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver()

        cmd = Command()
        # Should not raise
        cmd.handle(app_labels=[], name=None, check=False, empty=False, drop_columns=False)

    @patch("openviper.core.management.commands.makemigrations.AppResolver")
    @patch("openviper.core.management.commands.makemigrations.settings")
    def test_no_resolved_apps_check_only_outputs_no_changes(self, mock_settings, MockResolver):
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver()

        cmd = Command()
        stdout_calls = []
        with patch.object(cmd, "stdout", side_effect=lambda m: stdout_calls.append(m)):
            cmd.handle(app_labels=[], name=None, check=True, empty=False, drop_columns=False)

        combined = " ".join(stdout_calls)
        assert "no" in combined.lower() or "changes" in combined.lower()

    @patch("openviper.core.management.commands.makemigrations.AppResolver")
    @patch("openviper.core.management.commands.makemigrations.settings")
    def test_auto_detected_not_found_skips_silently(self, mock_settings, MockResolver):
        """Auto-discovered apps that can't be found are silently skipped."""
        mock_settings.INSTALLED_APPS = ["some.internal.app"]
        MockResolver.return_value = _make_resolver(resolved_apps={}, not_found=["internal.app"])

        cmd = Command()
        # should not raise
        cmd.handle(app_labels=[], name=None, check=False, empty=False, drop_columns=False)


# ---------------------------------------------------------------------------
# handle() – specific app_labels requested but not found
# ---------------------------------------------------------------------------


class TestHandleAppLabelsNotFound:
    @patch("openviper.core.management.commands.makemigrations.AppResolver")
    @patch("openviper.core.management.commands.makemigrations.settings")
    def test_all_app_labels_missing_returns_early(self, mock_settings, MockResolver):
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(resolved_apps={}, not_found=["missing_app"])

        cmd = Command()
        stdout_calls = []
        with patch.object(cmd, "stdout", side_effect=lambda m: stdout_calls.append(m)):
            with patch(
                "openviper.core.management.commands.makemigrations.AppResolver.print_app_not_found_error"
            ):
                cmd.handle(
                    app_labels=["missing_app"],
                    name=None,
                    check=False,
                    empty=False,
                    drop_columns=False,
                )

        combined = " ".join(stdout_calls)
        assert "missing_app" in combined or "Error" in combined

    @patch("openviper.core.management.commands.makemigrations.AppResolver")
    @patch("openviper.core.management.commands.makemigrations.settings")
    @patch(
        "openviper.core.management.commands.makemigrations.has_model_changes", return_value=False
    )
    def test_partial_not_found_continues_with_found(self, mock_hmc, mock_settings, MockResolver):
        """Some apps found, some not -> process found apps, report errors for missing."""
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(
            resolved_apps={"myapp": "/path/to/myapp"},
            not_found=["missing_app"],
        )

        cmd = Command()
        with patch(
            "openviper.core.management.commands.makemigrations.AppResolver.print_app_not_found_error"
        ):
            with patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                side_effect=ImportError,
            ):
                cmd.handle(
                    app_labels=["myapp", "missing_app"],
                    name=None,
                    check=False,
                    empty=False,
                    drop_columns=False,
                )


# ---------------------------------------------------------------------------
# handle() – empty migration
# ---------------------------------------------------------------------------


class TestHandleEmptyMigration:
    @patch("openviper.core.management.commands.makemigrations.AppResolver")
    @patch("openviper.core.management.commands.makemigrations.settings")
    @patch("openviper.core.management.commands.makemigrations.write_initial_migration")
    @patch(
        "openviper.core.management.commands.makemigrations.next_migration_number",
        return_value="1",
    )
    @patch(
        "openviper.core.management.commands.makemigrations.has_model_changes",
        return_value=True,
    )
    def test_empty_flag_creates_initial_migration(
        self, mock_hmc, mock_num, mock_write, mock_settings, MockResolver
    ):
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(resolved_apps={"testapp": "/path/to/testapp"})

        cmd = Command()
        cmd.handle(app_labels=["testapp"], name=None, check=False, empty=True, drop_columns=False)

        mock_write.assert_called_once()
        args = mock_write.call_args[0]
        assert args[0] == "testapp"

    @patch("openviper.core.management.commands.makemigrations.AppResolver")
    @patch("openviper.core.management.commands.makemigrations.settings")
    @patch("openviper.core.management.commands.makemigrations.write_initial_migration")
    @patch(
        "openviper.core.management.commands.makemigrations.next_migration_number",
        return_value="2",
    )
    @patch(
        "openviper.core.management.commands.makemigrations.has_model_changes",
        return_value=True,
    )
    def test_empty_flag_with_custom_name(
        self, mock_hmc, mock_num, mock_write, mock_settings, MockResolver
    ):
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(resolved_apps={"testapp": "/path/to/testapp"})

        cmd = Command()
        cmd.handle(
            app_labels=["testapp"], name="myempty", check=False, empty=True, drop_columns=False
        )

        call_kwargs = mock_write.call_args[1]
        assert "myempty" in call_kwargs.get("migration_name", "")


# ---------------------------------------------------------------------------
# handle() – initial migration (migration number == 1)
# ---------------------------------------------------------------------------


class TestHandleInitialMigration:
    @patch("openviper.core.management.commands.makemigrations.AppResolver")
    @patch("openviper.core.management.commands.makemigrations.settings")
    @patch("openviper.core.management.commands.makemigrations.write_initial_migration")
    @patch(
        "openviper.core.management.commands.makemigrations.next_migration_number",
        return_value="1",
    )
    @patch(
        "openviper.core.management.commands.makemigrations.has_model_changes",
        return_value=True,
    )
    def test_num1_writes_initial_migration(
        self, mock_hmc, mock_num, mock_write, mock_settings, MockResolver
    ):
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(resolved_apps={"testapp": "/path/to/testapp"})
        mod = MagicMock()
        mod.__name__ = "testapp.models"

        with (
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
            ),
            patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ),
        ):
            cmd = Command()
            cmd.handle(
                app_labels=["testapp"],
                name=None,
                check=False,
                empty=False,
                drop_columns=False,
            )

        mock_write.assert_called_once()
        # migration name should include "initial"
        call_kwargs = mock_write.call_args[1]
        assert "initial" in call_kwargs.get("migration_name", "")

    @patch("openviper.core.management.commands.makemigrations.AppResolver")
    @patch("openviper.core.management.commands.makemigrations.settings")
    @patch("openviper.core.management.commands.makemigrations.write_initial_migration")
    @patch(
        "openviper.core.management.commands.makemigrations.next_migration_number",
        return_value="1",
    )
    @patch(
        "openviper.core.management.commands.makemigrations.has_model_changes",
        return_value=True,
    )
    def test_num1_with_custom_name(
        self, mock_hmc, mock_num, mock_write, mock_settings, MockResolver
    ):
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(resolved_apps={"testapp": "/path/to/testapp"})
        mod = MagicMock()
        mod.__name__ = "testapp.models"

        with (
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
            ),
            patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ),
        ):
            cmd = Command()
            cmd.handle(
                app_labels=["testapp"],
                name="setup",
                check=False,
                empty=False,
                drop_columns=False,
            )

        call_kwargs = mock_write.call_args[1]
        assert "setup" in call_kwargs.get("migration_name", "")


# ---------------------------------------------------------------------------
# handle() – subsequent migrations (migration number > 1)
# ---------------------------------------------------------------------------


class TestHandleSubsequentMigration:
    @patch("openviper.core.management.commands.makemigrations.AppResolver")
    @patch("openviper.core.management.commands.makemigrations.settings")
    @patch("openviper.core.management.commands.makemigrations.write_migration")
    @patch(
        "openviper.core.management.commands.makemigrations.next_migration_number",
        return_value="2",
    )
    @patch(
        "openviper.core.management.commands.makemigrations.has_model_changes",
        return_value=True,
    )
    @patch("openviper.core.management.commands.makemigrations._diff_states")
    @patch("openviper.core.management.commands.makemigrations.model_state_snapshot")
    @patch("openviper.core.management.commands.makemigrations.read_migrated_state")
    def test_writes_migration_when_changes_exist(
        self,
        mock_rms,
        mock_mss,
        mock_diff,
        mock_hmc,
        mock_num,
        mock_write,
        mock_settings,
        MockResolver,
    ):
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(resolved_apps={"testapp": "/path/to/testapp"})
        mod = MagicMock()
        mod.__name__ = "testapp.models"
        mock_diff.return_value = [AddColumn(table_name="t", column_name="bio", column_type="TEXT")]

        with (
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
            ),
            patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ),
        ):
            cmd = Command()
            cmd.handle(
                app_labels=["testapp"],
                name=None,
                check=False,
                empty=False,
                drop_columns=False,
            )

        mock_write.assert_called_once()

    @patch("openviper.core.management.commands.makemigrations.AppResolver")
    @patch("openviper.core.management.commands.makemigrations.settings")
    @patch("openviper.core.management.commands.makemigrations.write_migration")
    @patch(
        "openviper.core.management.commands.makemigrations.next_migration_number",
        return_value="2",
    )
    @patch(
        "openviper.core.management.commands.makemigrations.has_model_changes",
        return_value=True,
    )
    @patch("openviper.core.management.commands.makemigrations._diff_states")
    @patch("openviper.core.management.commands.makemigrations.model_state_snapshot")
    @patch("openviper.core.management.commands.makemigrations.read_migrated_state")
    @patch("openviper.core.management.commands.makemigrations.importlib.import_module")
    def test_no_ops_skips_writing(
        self,
        mock_import,
        mock_rms,
        mock_mss,
        mock_diff,
        mock_hmc,
        mock_num,
        mock_write,
        mock_settings,
        MockResolver,
    ):
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(resolved_apps={"testapp": "/path/to/testapp"})
        mod = MagicMock()
        mod.__name__ = "testapp.models"
        mock_import.return_value = mod
        mock_diff.return_value = []  # no differences

        with patch(
            "openviper.core.management.commands.makemigrations.inspect.getmembers",
            return_value=[],
        ):
            cmd = Command()
            cmd.handle(
                app_labels=["testapp"],
                name=None,
                check=False,
                empty=False,
                drop_columns=False,
            )

        mock_write.assert_not_called()

    @patch("openviper.core.management.commands.makemigrations.AppResolver")
    @patch("openviper.core.management.commands.makemigrations.settings")
    @patch("openviper.core.management.commands.makemigrations.write_migration")
    @patch(
        "openviper.core.management.commands.makemigrations.next_migration_number",
        return_value="2",
    )
    @patch(
        "openviper.core.management.commands.makemigrations.has_model_changes",
        return_value=True,
    )
    @patch("openviper.core.management.commands.makemigrations._diff_states")
    @patch("openviper.core.management.commands.makemigrations.model_state_snapshot")
    @patch("openviper.core.management.commands.makemigrations.read_migrated_state")
    def test_drop_columns_sets_drop_true_on_remove_column_ops(
        self,
        mock_rms,
        mock_mss,
        mock_diff,
        mock_hmc,
        mock_num,
        mock_write,
        mock_settings,
        MockResolver,
    ):
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(resolved_apps={"testapp": "/path/to/testapp"})
        mod = MagicMock()
        mod.__name__ = "testapp.models"

        rc_op = RemoveColumn(table_name="t", column_name="old_col")
        mock_diff.return_value = [rc_op]

        with (
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
            ),
            patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ),
        ):
            cmd = Command()
            cmd.handle(
                app_labels=["testapp"],
                name=None,
                check=False,
                empty=False,
                drop_columns=True,
            )

        assert rc_op.drop is True
        mock_write.assert_called_once()

    @patch("openviper.core.management.commands.makemigrations.AppResolver")
    @patch("openviper.core.management.commands.makemigrations.settings")
    @patch("openviper.core.management.commands.makemigrations.write_migration")
    @patch(
        "openviper.core.management.commands.makemigrations.next_migration_number",
        return_value="2",
    )
    @patch(
        "openviper.core.management.commands.makemigrations.has_model_changes",
        return_value=True,
    )
    @patch("openviper.core.management.commands.makemigrations._diff_states")
    @patch("openviper.core.management.commands.makemigrations.model_state_snapshot")
    @patch("openviper.core.management.commands.makemigrations.read_migrated_state")
    def test_custom_name_used_in_migration_name(
        self,
        mock_rms,
        mock_mss,
        mock_diff,
        mock_hmc,
        mock_num,
        mock_write,
        mock_settings,
        MockResolver,
    ):
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(resolved_apps={"testapp": "/path/to/testapp"})
        mod = MagicMock()
        mod.__name__ = "testapp.models"
        mock_diff.return_value = [AddColumn(table_name="t", column_name="bio", column_type="TEXT")]

        with (
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
            ),
            patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ),
        ):
            cmd = Command()
            cmd.handle(
                app_labels=["testapp"],
                name="my_custom",
                check=False,
                empty=False,
                drop_columns=False,
            )

        call_kwargs = mock_write.call_args[1]
        assert "my_custom" in call_kwargs.get("migration_name", "")


# ---------------------------------------------------------------------------
# handle() – check only mode
# ---------------------------------------------------------------------------


class TestHandleCheckOnly:
    @patch("openviper.core.management.commands.makemigrations.AppResolver")
    @patch("openviper.core.management.commands.makemigrations.settings")
    @patch(
        "openviper.core.management.commands.makemigrations.has_model_changes",
        return_value=True,
    )
    @patch(
        "openviper.core.management.commands.makemigrations.next_migration_number",
        return_value="2",
    )
    def test_check_with_changes_exits_nonzero(
        self, mock_num, mock_hmc, mock_settings, MockResolver
    ):
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(resolved_apps={"testapp": "/path/to/testapp"})
        mod = MagicMock()
        mod.__name__ = "testapp.models"

        with (
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
            ),
            patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ),
        ):
            cmd = Command()
            with pytest.raises(SystemExit) as exc_info:
                cmd.handle(
                    app_labels=["testapp"],
                    name=None,
                    check=True,
                    empty=False,
                    drop_columns=False,
                )
            assert exc_info.value.code == 1

    @patch("openviper.core.management.commands.makemigrations.AppResolver")
    @patch("openviper.core.management.commands.makemigrations.settings")
    @patch(
        "openviper.core.management.commands.makemigrations.has_model_changes",
        return_value=False,
    )
    def test_check_no_changes_does_not_exit(self, mock_hmc, mock_settings, MockResolver):
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(resolved_apps={"testapp": "/path/to/testapp"})
        mod = MagicMock()
        mod.__name__ = "testapp.models"

        with (
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
            ),
            patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ),
            patch("sys.exit") as mock_exit,
        ):
            cmd = Command()
            cmd.handle(
                app_labels=["testapp"],
                name=None,
                check=True,
                empty=False,
                drop_columns=False,
            )
            mock_exit.assert_not_called()


# ---------------------------------------------------------------------------
# handle() – no_changes_detected path
# ---------------------------------------------------------------------------


class TestHandleNoModelChanges:
    @patch("openviper.core.management.commands.makemigrations.AppResolver")
    @patch("openviper.core.management.commands.makemigrations.settings")
    @patch(
        "openviper.core.management.commands.makemigrations.has_model_changes",
        return_value=False,
    )
    def test_no_changes_outputs_notice(self, mock_hmc, mock_settings, MockResolver):
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(resolved_apps={"testapp": "/path/to/testapp"})
        mod = MagicMock()
        mod.__name__ = "testapp.models"

        stdout_calls = []
        with (
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
            ),
            patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ),
        ):
            cmd = Command()
            with patch.object(cmd, "stdout", side_effect=lambda m: stdout_calls.append(m)):
                cmd.handle(
                    app_labels=["testapp"],
                    name=None,
                    check=False,
                    empty=False,
                    drop_columns=False,
                )

        combined = " ".join(stdout_calls)
        assert "no changes" in combined.lower() or "0" in combined


# ---------------------------------------------------------------------------
# handle() – model import fallback logic
# ---------------------------------------------------------------------------


class TestHandleModelImport:
    @patch("openviper.core.management.commands.makemigrations.AppResolver")
    @patch("openviper.core.management.commands.makemigrations.settings")
    @patch("openviper.core.management.commands.makemigrations.write_initial_migration")
    @patch(
        "openviper.core.management.commands.makemigrations.next_migration_number",
        return_value="1",
    )
    @patch(
        "openviper.core.management.commands.makemigrations.has_model_changes",
        return_value=True,
    )
    def test_both_imports_fail_no_model_classes(
        self, mock_hmc, mock_num, mock_write, mock_settings, MockResolver
    ):
        """When both import attempts fail, model_classes=[]; migration still created."""
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(resolved_apps={"testapp": "/path/to/testapp"})

        def fail_import(module_name):
            raise ImportError(f"cannot import {module_name}")

        with patch(
            "openviper.core.management.commands.makemigrations.importlib.import_module",
            side_effect=fail_import,
        ):
            cmd = Command()
            cmd.handle(
                app_labels=["testapp"],
                name=None,
                check=False,
                empty=False,
                drop_columns=False,
            )

        mock_write.assert_called_once()

    @patch("openviper.core.management.commands.makemigrations.AppResolver")
    @patch("openviper.core.management.commands.makemigrations.settings")
    @patch("openviper.core.management.commands.makemigrations.write_initial_migration")
    @patch(
        "openviper.core.management.commands.makemigrations.next_migration_number",
        return_value="1",
    )
    @patch(
        "openviper.core.management.commands.makemigrations.has_model_changes",
        return_value=True,
    )
    def test_first_import_fails_second_succeeds(
        self, mock_hmc, mock_num, mock_write, mock_settings, MockResolver
    ):
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(resolved_apps={"testapp": "/path/to/testapp"})

        fallback_mod = MagicMock()
        fallback_mod.__name__ = "models"

        call_count = [0]

        def selective_import(module_name):
            call_count[0] += 1
            if module_name == "testapp.models":
                raise ImportError("not found")
            return fallback_mod

        with (
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                side_effect=selective_import,
            ),
            patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ),
        ):
            cmd = Command()
            cmd.handle(
                app_labels=["testapp"],
                name=None,
                check=False,
                empty=False,
                drop_columns=False,
            )

        mock_write.assert_called_once()

    @patch("openviper.core.management.commands.makemigrations.AppResolver")
    @patch("openviper.core.management.commands.makemigrations.settings")
    @patch("openviper.core.management.commands.makemigrations.write_initial_migration")
    @patch(
        "openviper.core.management.commands.makemigrations.next_migration_number",
        return_value="1",
    )
    @patch(
        "openviper.core.management.commands.makemigrations.has_model_changes",
        return_value=True,
    )
    def test_abstract_models_skipped(
        self, mock_hmc, mock_num, mock_write, mock_settings, MockResolver
    ):
        """Abstract model classes should not appear in model_classes."""
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(resolved_apps={"testapp": "/path/to/testapp"})
        mod = MagicMock()
        mod.__name__ = "testapp.models"

        # Use a lightweight fake base class to avoid importing openviper.db.models.Model
        class FakeModelBase:
            pass

        class AbstractModel(FakeModelBase):
            __module__ = "testapp.models"

            class Meta:
                abstract = True

        # Patch `Model` in makemigrations so `issubclass(AbstractModel, FakeModelBase)` works
        with (
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
            ),
            patch("openviper.core.management.commands.makemigrations.Model", FakeModelBase),
            patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[("AbstractModel", AbstractModel)],
            ),
        ):
            cmd = Command()
            cmd.handle(
                app_labels=["testapp"],
                name=None,
                check=False,
                empty=False,
                drop_columns=False,
            )

        # write_initial_migration should be called with empty model_classes
        mock_write.assert_called_once()
        model_classes_arg = mock_write.call_args[0][1]
        assert AbstractModel not in model_classes_arg

    @patch("openviper.core.management.commands.makemigrations.AppResolver")
    @patch("openviper.core.management.commands.makemigrations.settings")
    def test_migrations_dir_none_skips_app(self, mock_settings, MockResolver):
        """If get_migrations_dir returns None, the app is skipped."""
        mock_settings.INSTALLED_APPS = []
        resolver = MagicMock()
        resolver.resolve_all_apps.return_value = {
            "found": {"testapp": "/path/to/testapp"},
            "not_found": [],
        }
        resolver.get_migrations_dir.return_value = None  # no migrations dir
        MockResolver.return_value = resolver

        cmd = Command()
        # Should not raise; app is silently skipped
        cmd.handle(
            app_labels=["testapp"],
            name=None,
            check=False,
            empty=False,
            drop_columns=False,
        )


# ---------------------------------------------------------------------------
# Topological sort – cycle detection
# ---------------------------------------------------------------------------


class TestTopologicalSort:
    @patch("openviper.core.management.commands.makemigrations.AppResolver")
    @patch("openviper.core.management.commands.makemigrations.settings")
    @patch(
        "openviper.core.management.commands.makemigrations.has_model_changes", return_value=False
    )
    @patch("openviper.core.management.commands.makemigrations.importlib.import_module")
    def test_multiple_apps_sorted_and_processed(
        self, mock_import, mock_hmc, mock_settings, MockResolver
    ):
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(
            resolved_apps={
                "appa": "/path/to/appa",
                "appb": "/path/to/appb",
            }
        )
        mod = MagicMock()
        mod.__name__ = "models"
        mock_import.return_value = mod

        with patch(
            "openviper.core.management.commands.makemigrations.inspect.getmembers",
            return_value=[],
        ):
            cmd = Command()
            # Should process both apps without error
            cmd.handle(
                app_labels=["appa", "appb"],
                name=None,
                check=False,
                empty=False,
                drop_columns=False,
            )
