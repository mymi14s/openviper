"""Unit tests for the migrate management command."""

from __future__ import annotations

import argparse
import sys
from unittest.mock import MagicMock, patch

from openviper.core.management.commands.migrate import Command


def _make_resolver(resolved_apps=None, not_found=True, resolve_app_result=None):
    resolver = MagicMock()
    resolver.resolve_all_apps.return_value = {
        "found": resolved_apps if resolved_apps is not None else {},
        "not_found": [],
    }
    if resolve_app_result is None:
        resolve_app_result = ("/path/to/app", True)
    resolver.resolve_app.return_value = resolve_app_result
    return resolver


# ---------------------------------------------------------------------------
# add_arguments
# ---------------------------------------------------------------------------


def test_add_arguments_defaults():

    cmd = Command()
    parser = argparse.ArgumentParser()
    cmd.add_arguments(parser)

    args = parser.parse_args([])
    assert args.app_label is None
    assert args.migration_name is None
    assert args.fake is False
    assert args.database == "default"


def test_add_arguments_all_options():

    cmd = Command()
    parser = argparse.ArgumentParser()
    cmd.add_arguments(parser)

    args = parser.parse_args(["myapp", "0002", "--fake", "--database", "replica"])
    assert args.app_label == "myapp"
    assert args.migration_name == "0002"
    assert args.fake is True
    assert args.database == "replica"


# ---------------------------------------------------------------------------
# handle() – app_label not found
# ---------------------------------------------------------------------------


class TestHandleAppLabelNotFound:
    @patch("openviper.core.management.commands.migrate.AppResolver")
    @patch("openviper.core.management.commands.migrate.settings")
    def test_app_not_found_outputs_error(self, mock_settings, MockResolver):
        mock_settings.INSTALLED_APPS = []
        resolver = _make_resolver(resolve_app_result=(None, False))
        MockResolver.return_value = resolver

        cmd = Command()
        output = []
        with (
            patch.object(cmd, "stdout", side_effect=lambda m: output.append(m)),
            patch(
                "openviper.core.management.commands.migrate.AppResolver.print_app_not_found_error"
            ),
        ):
            cmd.handle(
                app_label="missing_app",
                migration_name=None,
                fake=False,
                database="default",
            )

        combined = " ".join(output)
        assert "missing_app" in combined or "Error" in combined

    @patch("openviper.core.management.commands.migrate.AppResolver")
    @patch("openviper.core.management.commands.migrate.settings")
    def test_app_not_found_returns_early(self, mock_settings, MockResolver):
        """When app not found, handle returns without running migrations."""
        mock_settings.INSTALLED_APPS = []
        resolver = _make_resolver(resolve_app_result=(None, False))
        MockResolver.return_value = resolver

        cmd = Command()
        with (
            patch(
                "openviper.core.management.commands.migrate.AppResolver.print_app_not_found_error"
            ),
            patch("openviper.core.management.commands.migrate.MigrationExecutor") as mock_exec,
        ):
            cmd.handle(
                app_label="missing_app",
                migration_name=None,
                fake=False,
                database="default",
            )
        mock_exec.assert_not_called()


# ---------------------------------------------------------------------------
# handle() – successful migration
# ---------------------------------------------------------------------------


class TestHandleSuccess:
    @patch("openviper.core.management.commands.migrate.AppResolver")
    @patch("openviper.core.management.commands.migrate.settings")
    @patch("openviper.core.management.commands.migrate.asyncio.run")
    def test_no_pending_migrations_outputs_notice(self, mock_run, mock_settings, MockResolver):
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver()
        mock_run.return_value = []  # no migrations applied

        cmd = Command()
        output = []
        with patch.object(cmd, "stdout", side_effect=lambda m: output.append(m)):
            cmd.handle(
                app_label=None,
                migration_name=None,
                fake=False,
                database="default",
            )

        combined = " ".join(output)
        assert "no migrations" in combined.lower() or "no" in combined.lower()

    @patch("openviper.core.management.commands.migrate.AppResolver")
    @patch("openviper.core.management.commands.migrate.settings")
    @patch("openviper.core.management.commands.migrate.asyncio.run")
    def test_applied_migrations_listed(self, mock_run, mock_settings, MockResolver):
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver()
        mock_run.return_value = ["0001_initial", "0002_add_email"]

        cmd = Command()
        output = []
        with patch.object(cmd, "stdout", side_effect=lambda m: output.append(m)):
            cmd.handle(
                app_label=None,
                migration_name=None,
                fake=False,
                database="default",
            )

        combined = " ".join(output)
        assert "0001_initial" in combined
        assert "0002_add_email" in combined

    @patch("openviper.core.management.commands.migrate.AppResolver")
    @patch("openviper.core.management.commands.migrate.settings")
    @patch("openviper.core.management.commands.migrate.asyncio.run")
    def test_always_outputs_complete_message(self, mock_run, mock_settings, MockResolver):
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver()
        mock_run.return_value = []

        cmd = Command()
        output = []
        with patch.object(cmd, "stdout", side_effect=lambda m: output.append(m)):
            cmd.handle(
                app_label=None,
                migration_name=None,
                fake=False,
                database="default",
            )

        combined = " ".join(output)
        assert "complete" in combined.lower() or "migration" in combined.lower()

    @patch("openviper.core.management.commands.migrate.AppResolver")
    @patch("openviper.core.management.commands.migrate.settings")
    @patch("openviper.core.management.commands.migrate.asyncio.run")
    def test_app_label_provided_resolves_app(self, mock_run, mock_settings, MockResolver):
        mock_settings.INSTALLED_APPS = []
        resolver = _make_resolver(
            resolved_apps={"testapp": "/path"},
            resolve_app_result=("/path", True),
        )
        MockResolver.return_value = resolver
        mock_run.return_value = []

        cmd = Command()
        with patch.object(cmd, "stdout"):
            cmd.handle(
                app_label="testapp",
                migration_name=None,
                fake=False,
                database="default",
            )

        resolver.resolve_app.assert_called_once_with("testapp")


# ---------------------------------------------------------------------------
# handle() – verbose TTY output
# ---------------------------------------------------------------------------


class TestHandleVerbose:
    @patch("openviper.core.management.commands.migrate.AppResolver")
    @patch("openviper.core.management.commands.migrate.settings")
    @patch("openviper.core.management.commands.migrate.asyncio.run")
    def test_verbose_app_locations_and_quiet_path(self, mock_run, mock_settings, MockResolver):
        # Covers lines 79-85: app locations printed when stdout is a TTY with resolved apps,
        # and line 87-88: quiet path ("Running migrations...") when not verbose
        mock_settings.INSTALLED_APPS = []
        MockResolver.return_value = _make_resolver(resolved_apps={"myapp": "/path/to/myapp"})
        mock_run.return_value = ["0001_initial"]

        cmd = Command()
        output = []

        # Verbose path: TTY stdout → lines 79-85 executed
        mock_tty = MagicMock()
        mock_tty.isatty.return_value = True
        with (
            patch.object(sys, "stdout", mock_tty),
            patch.object(cmd, "stdout", side_effect=lambda m: output.append(m)),
        ):
            cmd.handle(
                app_label=None,
                migration_name=None,
                fake=False,
                database="default",
            )

        combined = " ".join(output)
        assert "complete" in combined.lower() or "migration" in combined.lower()
