"""Tests for the viperctl Click command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from openviper.viperctl import viperctl


class TestViperctlCommand:
    """Tests for the viperctl Click command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_unknown_command_rejected(self, runner: CliRunner) -> None:
        """Passing an unsupported command name produces an error."""
        result = runner.invoke(viperctl, ["badcommand"])
        assert result.exit_code != 0
        assert "Unknown command" in result.output

    def test_valid_commands_accepted(self, runner: CliRunner, tmp_path: Path) -> None:
        """All supported commands pass validation (before bootstrap)."""
        valid_commands = [
            "makemigrations",
            "migrate",
            "shell",
            "runworker",
            "collectstatic",
            "test",
            "createsuperuser",
            "changepassword",
        ]
        for cmd in valid_commands:
            with (
                patch("openviper.management.flexible_adapter.bootstrap_and_run") as mock_run,
                patch("openviper.utils.module_resolver.resolve_target") as mock_resolve,
                patch(
                    "openviper.utils.settings_discovery.discover_settings_module"
                ) as mock_discover,
            ):
                from openviper.utils.module_resolver import ResolvedModule

                mock_resolve.return_value = ResolvedModule(
                    app_label="test",
                    app_path=tmp_path,
                    is_root=True,
                    models_module="test.models",
                )
                mock_discover.return_value = "settings"

                runner.invoke(viperctl, [cmd])
                assert mock_run.called, f"Command '{cmd}' should call bootstrap_and_run"

    def test_settings_option_passed_through(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """--settings value is forwarded to discover_settings_module."""
        with (
            patch("openviper.management.flexible_adapter.bootstrap_and_run"),
            patch("openviper.utils.module_resolver.resolve_target") as mock_resolve,
            patch("openviper.utils.settings_discovery.discover_settings_module") as mock_discover,
        ):
            from openviper.utils.module_resolver import ResolvedModule

            mock_resolve.return_value = ResolvedModule(
                app_label="test",
                app_path=tmp_path,
                is_root=True,
                models_module="test.models",
            )
            mock_discover.return_value = "custom.settings"

            runner.invoke(viperctl, ["--settings", "custom.settings", "shell"])

            mock_discover.assert_called_once()
            call_kwargs = mock_discover.call_args
            assert call_kwargs[1]["explicit"] == "custom.settings"

    def test_target_argument_forwarded(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Target argument is forwarded to resolve_target."""
        with (
            patch("openviper.management.flexible_adapter.bootstrap_and_run"),
            patch("openviper.utils.module_resolver.resolve_target") as mock_resolve,
            patch("openviper.utils.settings_discovery.discover_settings_module"),
        ):
            from openviper.utils.module_resolver import ResolvedModule

            mock_resolve.return_value = ResolvedModule(
                app_label="todo",
                app_path=tmp_path / "todo",
                is_root=False,
                models_module="todo.models",
            )

            runner.invoke(viperctl, ["makemigrations", "todo"])

            mock_resolve.assert_called_once()
            assert mock_resolve.call_args[0][0] == "todo"

    def test_default_target_is_dot(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """When no target is provided, defaults to '.'."""
        with (
            patch("openviper.management.flexible_adapter.bootstrap_and_run"),
            patch("openviper.utils.module_resolver.resolve_target") as mock_resolve,
            patch("openviper.utils.settings_discovery.discover_settings_module"),
        ):
            from openviper.utils.module_resolver import ResolvedModule

            mock_resolve.return_value = ResolvedModule(
                app_label="test",
                app_path=tmp_path,
                is_root=True,
                models_module="test.models",
            )

            runner.invoke(viperctl, ["shell"])

            mock_resolve.assert_called_once()
            assert mock_resolve.call_args[0][0] == "."

    def test_extra_args_captured(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Extra CLI arguments are passed through as command_args."""
        with (
            patch("openviper.management.flexible_adapter.bootstrap_and_run") as mock_run,
            patch("openviper.utils.module_resolver.resolve_target") as mock_resolve,
            patch("openviper.utils.settings_discovery.discover_settings_module"),
        ):
            from openviper.utils.module_resolver import ResolvedModule

            mock_resolve.return_value = ResolvedModule(
                app_label="test",
                app_path=tmp_path,
                is_root=True,
                models_module="test.models",
            )

            runner.invoke(
                viperctl,
                ["makemigrations", ".", "--name", "custom_migration"],
            )

            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args[1]
            assert "--name" in call_kwargs["command_args"]
            assert "custom_migration" in call_kwargs["command_args"]


class TestViperctlRegistration:
    """Test that viperctl is registered with the main CLI group."""

    def test_cli_has_viperctl_command(self) -> None:
        """The main CLI group includes the viperctl subcommand."""
        from openviper.cli import cli

        assert "viperctl" in cli.commands  # type: ignore[attr-defined]
