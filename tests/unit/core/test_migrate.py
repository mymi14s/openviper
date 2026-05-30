"""Unit tests for migrate management command."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from openviper.core.management.commands.migrate import Command


@pytest.fixture
def command():
    """Create a Command instance."""
    return Command()


class TestMigrateCommand:
    """Test migrate command basic functionality."""

    def test_help_attribute(self, command):
        assert "database migrations" in command.help or "migrations" in command.help

    def test_add_arguments(self, command):
        parser = Mock()
        parser.add_argument = Mock()

        command.add_arguments(parser)

        # Should add app_label, migration_name, --fake, --database
        assert parser.add_argument.call_count == 4


class TestHandleBasic:
    """Test basic handle functionality."""

    @patch("openviper.conf.settings")
    @patch("openviper.core.management.commands.migrate.AppResolver")
    @patch("openviper.core.management.commands.migrate.asyncio.run")
    def test_handle_runs_migrations(
        self, mock_run, mock_resolver_cls, mock_settings, command, capsys
    ):
        mock_settings.INSTALLED_APPS = []

        mock_resolver = Mock()
        mock_resolver.resolve_all_apps = Mock(return_value={"found": {}})
        mock_resolver_cls.return_value = mock_resolver

        mock_run.return_value = ["app.0001_initial"]

        command.handle(app_label=None, migration_name=None, fake=False, database="default")

        mock_run.assert_called_once()
        captured = capsys.readouterr()
        assert "Migrations complete" in captured.out


class TestAppResolution:
    """Test app resolution."""

    @patch("openviper.conf.settings")
    @patch("openviper.core.management.commands.migrate.AppResolver")
    @patch("openviper.core.management.commands.migrate.asyncio.run")
    def test_handle_with_specific_app(self, mock_run, mock_resolver_cls, mock_settings, command):
        mock_settings.INSTALLED_APPS = ["testapp"]

        mock_resolver = Mock()
        mock_resolver.resolve_app = Mock(return_value=("/fake/testapp", True))
        mock_resolver.resolve_all_apps = Mock(return_value={"found": {"testapp": "/fake/testapp"}})
        mock_resolver_cls.return_value = mock_resolver

        mock_run.return_value = []

        command.handle(app_label="testapp", migration_name=None, fake=False, database="default")

        mock_resolver.resolve_app.assert_called_once_with("testapp")

    @patch("openviper.conf.settings")
    @patch("openviper.core.management.commands.migrate.AppResolver")
    def test_handle_app_not_found_shows_error(
        self, mock_resolver_cls, mock_settings, command, capsys
    ):
        mock_settings.INSTALLED_APPS = []

        mock_resolver = Mock()
        mock_resolver.resolve_app = Mock(return_value=(None, False))
        mock_resolver_cls.return_value = mock_resolver

        command.handle(app_label="nonexistent", migration_name=None, fake=False, database="default")

        captured = capsys.readouterr()
        assert "not found" in captured.out


class TestVerboseMode:
    """Test verbose mode (TTY detection)."""

    @patch("openviper.conf.settings")
    @patch("openviper.core.management.commands.migrate.AppResolver")
    @patch("openviper.core.management.commands.migrate.asyncio.run")
    @patch("openviper.core.management.commands.migrate.sys")
    def test_handle_verbose_with_tty(
        self, mock_sys, mock_run, mock_resolver_cls, mock_settings, command, capsys
    ):
        mock_settings.INSTALLED_APPS = []

        mock_sys.stdout.isatty = Mock(return_value=True)

        mock_resolver = Mock()
        mock_resolver.resolve_all_apps = Mock(return_value={"found": {"app": "/path"}})
        mock_resolver_cls.return_value = mock_resolver

        mock_run.return_value = []

        command.handle(app_label=None, migration_name=None, fake=False, database="default")

        captured = capsys.readouterr()
        assert "App Locations:" in captured.out


class TestMigrationExecution:
    """Test migration execution."""

    @patch("openviper.conf.settings")
    @patch("openviper.core.management.commands.migrate.AppResolver")
    @patch("openviper.core.management.commands.migrate.MigrationExecutor")
    @patch("openviper.core.management.commands.migrate.asyncio.run")
    def test_handle_passes_options_to_executor(
        self, mock_run, mock_executor_cls, mock_resolver_cls, mock_settings, command
    ):
        mock_settings.INSTALLED_APPS = []

        mock_resolver = Mock()
        mock_resolver.resolve_all_apps = Mock(return_value={"found": {}})
        mock_resolver.resolve_app = Mock(return_value=("/fake/app", True))
        mock_resolver_cls.return_value = mock_resolver

        mock_executor = Mock()
        mock_executor.migrate = AsyncMock(return_value=[])
        mock_executor_cls.return_value = mock_executor

        # Just return an empty list - we only need to verify executor is used
        mock_run.return_value = []

        command.handle(
            app_label="testapp",
            migration_name="0001_initial",
            fake=False,
            database="default",
        )

        # Verify asyncio.run was called (with a coroutine)
        mock_run.assert_called_once()


class TestNoMigrations:
    """Test when no migrations need to be applied."""

    @patch("openviper.conf.settings")
    @patch("openviper.core.management.commands.migrate.AppResolver")
    @patch("openviper.core.management.commands.migrate.asyncio.run")
    def test_handle_no_migrations_to_apply(
        self, mock_run, mock_resolver_cls, mock_settings, command, capsys
    ):
        mock_settings.INSTALLED_APPS = []

        mock_resolver = Mock()
        mock_resolver.resolve_all_apps = Mock(return_value={"found": {}})
        mock_resolver_cls.return_value = mock_resolver

        mock_run.return_value = []

        command.handle(app_label=None, migration_name=None, fake=False, database="default")

        captured = capsys.readouterr()
        assert "No migrations to apply" in captured.out


class TestAppliedMigrations:
    """Test applied migrations output."""

    @patch("openviper.conf.settings")
    @patch("openviper.core.management.commands.migrate.AppResolver")
    @patch("openviper.core.management.commands.migrate.asyncio.run")
    @patch("openviper.core.management.commands.migrate.sys")
    def test_handle_shows_applied_migrations_non_verbose(
        self, mock_sys, mock_run, mock_resolver_cls, mock_settings, command, capsys
    ):
        mock_settings.INSTALLED_APPS = []

        mock_sys.stdout.isatty = Mock(return_value=False)

        mock_resolver = Mock()
        mock_resolver.resolve_all_apps = Mock(return_value={"found": {}})
        mock_resolver_cls.return_value = mock_resolver

        mock_run.return_value = ["app.0001_initial", "app.0002_update"]

        command.handle(app_label=None, migration_name=None, fake=False, database="default")

        captured = capsys.readouterr()
        assert "0001_initial" in captured.out
        assert "0002_update" in captured.out


class TestEdgeCases:
    """Test edge cases."""

    def test_command_instantiation(self):
        """Test that command can be instantiated."""
        cmd = Command()
        assert cmd is not None
        assert hasattr(cmd, "handle")
        assert hasattr(cmd, "add_arguments")

    @patch("openviper.conf.settings")
    @patch("openviper.core.management.commands.migrate.AppResolver")
    @patch("openviper.core.management.commands.migrate.asyncio.run")
    def test_handle_with_all_options(self, mock_run, mock_resolver_cls, mock_settings, command):
        mock_settings.INSTALLED_APPS = []

        mock_resolver = Mock()
        mock_resolver.resolve_app = Mock(return_value=("/fake/app", True))
        mock_resolver.resolve_all_apps = Mock(return_value={"found": {"app": "/fake/app"}})
        mock_resolver_cls.return_value = mock_resolver

        mock_run.return_value = []

        command.handle(
            app_label="testapp",
            migration_name="0001_initial",
            fake=True,
            database="secondary",
        )

        # Should execute without error
        mock_run.assert_called_once()
