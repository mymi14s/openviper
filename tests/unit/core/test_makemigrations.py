"""Unit tests for the makemigrations management command."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

import pytest

from openviper.core.management.commands.makemigrations import (
    _MAX_NAME_LENGTH,
    Command,
    _auto_migration_name,
)
from openviper.db.fields import ForeignKey
from openviper.db.migrations.executor import (
    AddColumn,
    AlterColumn,
    CreateTable,
    DropTable,
    RemoveColumn,
    RenameColumn,
    RestoreColumn,
)
from openviper.db.models import Model

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
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ),
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
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
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ),
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
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
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ),
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
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
    def test_no_ops_skips_writing(
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
        mock_diff.return_value = []  # no differences

        with (
            patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ),
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
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
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ),
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
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
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ),
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
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
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ),
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
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
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ),
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
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
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ),
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
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
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ),
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                side_effect=selective_import,
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

        class ConcreteModel(FakeModelBase):
            __module__ = "testapp.models"
            _fields = {}

        # Patch `Model` in makemigrations so `issubclass(AbstractModel, FakeModelBase)` works
        with (
            patch("openviper.core.management.commands.makemigrations.Model", FakeModelBase),
            patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[("AbstractModel", AbstractModel), ("ConcreteModel", ConcreteModel)],
            ),
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
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
    def test_multiple_apps_sorted_and_processed(
        self, mock_hmc, mock_settings, MockResolver
    ):
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(
            resolved_apps={
                "appa": "/path/to/appa",
                "appb": "/path/to/appb",
            }
        )

        # Build two models with mutual FK references to trigger cycle detection
        class _CycleA(Model):
            class Meta:
                table_name = "topo_test_cycle_a"

        class _CycleB(Model):
            class Meta:
                table_name = "topo_test_cycle_b"

        _CycleA.__module__ = "appa.models"
        _CycleB.__module__ = "appb.models"
        _CycleA._app_name = "appa"
        _CycleB._app_name = "appb"
        _CycleA._fields = {"ref": ForeignKey(to=_CycleB)}
        _CycleB._fields = {"ref": ForeignKey(to=_CycleA)}

        mod_a = MagicMock()
        mod_a.__name__ = "appa.models"
        mod_b = MagicMock()
        mod_b.__name__ = "appb.models"

        def _import(name, *a, **kw):
            return mod_a if "appa" in name else mod_b

        def _getmembers(mod, *a, **kw):
            return [("_CycleA", _CycleA)] if mod is mod_a else [("_CycleB", _CycleB)]

        with (
            patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                side_effect=_getmembers,
            ),
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                side_effect=_import,
            ),
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


# ---------------------------------------------------------------------------
# Model discovery – abstract model skipped
# ---------------------------------------------------------------------------


class TestAbstractModelSkip:
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
    def test_abstract_model_excluded_from_model_classes(
        self, mock_hmc, mock_num, mock_write, mock_settings, MockResolver
    ):
        class _AbstractModel(Model):
            class Meta:
                table_name = "abs_tbl"
                abstract = True

        _AbstractModel.__module__ = "testapp.models"

        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(resolved_apps={"testapp": "/path"})
        mod = MagicMock()
        mod.__name__ = "testapp.models"

        with (
            patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[("_AbstractModel", _AbstractModel)],
            ),
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
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

        # Abstract model skipped → write_initial_migration called with empty model_classes
        mock_write.assert_called_once()
        args = mock_write.call_args[0]
        assert args[1] == []  # model_classes is empty because abstract was filtered


# ---------------------------------------------------------------------------
# Model discovery – sys.path fallback import
# ---------------------------------------------------------------------------


class TestModelDiscoverySysPathFallback:
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
    def test_fallback_to_sys_path_import(
        self, mock_hmc, mock_num, mock_write, mock_settings, MockResolver
    ):
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(
            resolved_apps={"myapp": "/path/to/myapp"},
        )

        fallback_mod = MagicMock()
        fallback_mod.__name__ = "models"

        # Models whose __module__ matches fallback_mod.__name__ = "models"
        class _FallbackConcrete(Model):
            class Meta:
                table_name = "fallback_concrete_test"

        class _FallbackAbstract(Model):
            class Meta:
                table_name = "fallback_abstract_test"
                abstract = True

        _FallbackConcrete.__module__ = "models"
        _FallbackAbstract.__module__ = "models"

        def _selective_import(name, *args, **kwargs):
            if name == "myapp.models":
                raise ImportError("no app module")
            return fallback_mod

        with (
            patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[
                    ("_FallbackConcrete", _FallbackConcrete),
                    ("_FallbackAbstract", _FallbackAbstract),
                ],
            ),
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                side_effect=_selective_import,
            ),
        ):
            cmd = Command()
            cmd.handle(
                app_labels=["myapp"],
                name=None,
                check=False,
                empty=False,
                drop_columns=False,
            )

        mock_write.assert_called_once()


# ---------------------------------------------------------------------------
# Dependency analysis – cross-app FK and intra-app prev migration
# ---------------------------------------------------------------------------


class TestDependencyAnalysis:

    class _ModelB(Model):
        class Meta:
            table_name = "model_b"

    _ModelB._app_name = "appb"

    _fk_field = ForeignKey(to=_ModelB)
    _fk_field.name = "ref"

    class _ModelA(Model):
        class Meta:
            table_name = "model_a"

    _ModelA._app_name = "appa"
    _ModelA._fields = {"ref": _fk_field}
    _ModelA.__module__ = "appa.models"
    _ModelB.__module__ = "appb.models"

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
    def test_cross_app_fk_dependency_detected(
        self, mock_hmc, mock_num, mock_write, mock_settings, MockResolver
    ):
        # Two apps: appa has a model whose FK points to appb model
        _ModelA = self.__class__._ModelA
        _ModelB = self.__class__._ModelB

        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(
            resolved_apps={"appa": "/path/appa", "appb": "/path/appb"},
        )

        mod_a = MagicMock()
        mod_a.__name__ = "appa.models"
        mod_b = MagicMock()
        mod_b.__name__ = "appb.models"

        def _import(name, *args, **kwargs):
            if "appa" in name:
                return mod_a
            return mod_b

        with (
            patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
            ) as mock_members,
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                side_effect=_import,
            ),
        ):
            mock_members.side_effect = lambda mod, *a, **kw: (
                [("_ModelA", _ModelA)] if mod is mod_a else [("_ModelB", _ModelB)]
            )
            cmd = Command()
            cmd.handle(
                app_labels=[],
                name=None,
                check=False,
                empty=False,
                drop_columns=False,
            )

        assert mock_write.call_count >= 1

    @patch("openviper.core.management.commands.makemigrations.AppResolver")
    @patch("openviper.core.management.commands.makemigrations.settings")
    @patch("openviper.core.management.commands.makemigrations.write_migration")
    @patch("openviper.core.management.commands.makemigrations._diff_states")
    @patch("openviper.core.management.commands.makemigrations.model_state_snapshot")
    @patch("openviper.core.management.commands.makemigrations.read_migrated_state")
    @patch(
        "openviper.core.management.commands.makemigrations.has_model_changes",
        return_value=True,
    )
    def test_intra_app_prev_migration_dep_and_inter_app_fk_dep(
        self, mock_hmc, mock_rms, mock_mss, mock_diff,
        mock_write, mock_settings, MockResolver, tmp_path
    ):
        # num=2 AND existing 0001 file → intra-app dep added
        # FK to other app with existing migrations → inter-app dep added
        mock_diff.return_value = [AddColumn(table_name="t", column_name="x", column_type="TEXT")]

        target_migs_dir = tmp_path / "appb_migrations"
        target_migs_dir.mkdir()
        (target_migs_dir / "0001_initial.py").write_text("")

        source_migs_dir = tmp_path / "appa_migrations"
        source_migs_dir.mkdir()
        (source_migs_dir / "0001_initial.py").write_text("")

        class _TargetModel(Model):
            class Meta:
                table_name = "target_model_dep_test"

        _TargetModel._app_name = "appb"

        fk_field = ForeignKey(to=_TargetModel)
        fk_field.name = "ref"

        class _SourceModel(Model):
            class Meta:
                table_name = "source_model_dep_test"

        _SourceModel._app_name = "appa"
        _SourceModel._fields = {"ref": fk_field}
        _SourceModel.__module__ = "appa.models"
        _TargetModel.__module__ = "appb.models"

        mock_settings.INSTALLED_APPS = []
        resolver = MagicMock()
        resolver.resolve_all_apps.return_value = {
            "found": {"appa": str(tmp_path / "appa")},
            "not_found": [],
        }
        resolver.get_migrations_dir.side_effect = lambda label: (
            str(source_migs_dir) if label == "appa" else str(target_migs_dir)
        )
        MockResolver.return_value = resolver

        mod_a = MagicMock()
        mod_a.__name__ = "appa.models"

        with (
            patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[("_SourceModel", _SourceModel)],
            ),
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod_a,
            ),
            patch(
                "openviper.core.management.commands.makemigrations.next_migration_number",
                return_value="2",
            ),
        ):
            cmd = Command()
            cmd.handle(
                app_labels=[],
                name=None,
                check=False,
                empty=False,
                drop_columns=False,
            )

        mock_write.assert_called_once()
        _args, kwargs = mock_write.call_args
        deps = kwargs.get("dependencies") or []
        assert any("appa" in str(d) or "0001" in str(d) for d in deps)


# ---------------------------------------------------------------------------
# Generation phase – empty migration with num>1 gets "initial" name
# and non-initial auto-name
# ---------------------------------------------------------------------------


class TestMigrationNaming:
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
    def test_empty_migration_num_gt1_gets_initial_name(
        self, mock_hmc, mock_num, mock_write, mock_settings, MockResolver
    ):
        # empty=True + num=2 + custom_name=None → name_part defaults to "initial"
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(resolved_apps={"testapp": "/path"})
        mod = MagicMock()
        mod.__name__ = "testapp.models"

        with (
            patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ),
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
            ),
        ):
            cmd = Command()
            cmd.handle(
                app_labels=["testapp"],
                name=None,
                check=False,
                empty=True,
                drop_columns=False,
            )

        mock_write.assert_called_once()
        _args, kwargs = mock_write.call_args
        assert "initial" in kwargs["migration_name"]  # migration_name kwarg

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
    def test_non_initial_migration_auto_named_from_ops(
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
        # num=2, custom_name=None, ops exist → name_part set by _auto_migration_name
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(resolved_apps={"testapp": "/path"})
        mod = MagicMock()
        mod.__name__ = "testapp.models"
        mock_diff.return_value = [AddColumn(table_name="t", column_name="bio", column_type="TEXT")]

        with (
            patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ),
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
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
        _args, kwargs = mock_write.call_args
        assert "add_bio" in kwargs["migration_name"]  # auto-named from AddColumn op

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
    def test_custom_name_used_in_non_initial_migration(
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
        # custom name provided via --name → used directly
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(resolved_apps={"testapp": "/path"})
        mod = MagicMock()
        mod.__name__ = "testapp.models"
        mock_diff.return_value = [AddColumn(table_name="t", column_name="bio", column_type="TEXT")]

        with (
            patch(
                "openviper.core.management.commands.makemigrations.inspect.getmembers",
                return_value=[],
            ),
            patch(
                "openviper.core.management.commands.makemigrations.importlib.import_module",
                return_value=mod,
            ),
        ):
            cmd = Command()
            cmd.handle(
                app_labels=["testapp"],
                name="custom_migration",
                check=False,
                empty=False,
                drop_columns=False,
            )

        mock_write.assert_called_once()
        _args, kwargs = mock_write.call_args
        assert "custom_migration" in kwargs["migration_name"]
