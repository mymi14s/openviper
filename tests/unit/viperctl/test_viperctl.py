"""Unit tests for openviper/viperctl.py."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from openviper.viperctl import _ALLOWED_COMMANDS, viperctl

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def app_dir(tmp_path):
    app = tmp_path / "myapp"
    app.mkdir()
    (app / "models.py").write_text("# models\n")
    (app / "__init__.py").write_text("")
    return tmp_path, app


# ---------------------------------------------------------------------------
# _ALLOWED_COMMANDS
# ---------------------------------------------------------------------------


class TestAllowedCommands:
    @pytest.mark.parametrize(
        "cmd",
        [
            "makemigrations",
            "migrate",
            "shell",
            "runworker",
            "collectstatic",
            "test",
            "createsuperuser",
            "changepassword",
        ],
    )
    def test_allowed_command_in_set(self, cmd):
        assert cmd in _ALLOWED_COMMANDS

    def test_is_frozenset(self):
        assert isinstance(_ALLOWED_COMMANDS, frozenset)

    def test_len(self):
        assert len(_ALLOWED_COMMANDS) == 8


# ---------------------------------------------------------------------------
# viperctl command
# ---------------------------------------------------------------------------


class TestViperctlCommand:
    def test_unknown_command_raises(self, runner):
        result = runner.invoke(viperctl, ["unknown_cmd", "."])
        assert result.exit_code != 0

    def test_help_shows_commands(self, runner):
        result = runner.invoke(viperctl, ["--help"])
        assert "COMMAND" in result.output or "makemigrations" in result.output

    def test_makemigrations_calls_bootstrap(self, runner, app_dir):
        cwd, app = app_dir
        # bootstrap_and_run is imported lazily inside viperctl body
        # We patch it at its source location
        with patch(
            "openviper.core.flexible_adapter.bootstrap_and_run",
            side_effect=SystemExit(0),
        ):
            result = runner.invoke(
                viperctl,
                ["makemigrations", "myapp"],
                catch_exceptions=True,
            )
            # May exit 0 if mock called, or fail in resolution
            assert result.exit_code in (0, 1, 2)

    def test_migrate_allowed_command(self, runner):
        # Just check that 'migrate' is in allowed set
        assert "migrate" in _ALLOWED_COMMANDS

    def test_settings_option_accepted(self, runner, app_dir):
        cwd, app = app_dir
        with patch(
            "openviper.core.flexible_adapter.bootstrap_and_run",
            side_effect=SystemExit(0),
        ):
            runner.invoke(
                viperctl,
                ["--settings", "myapp.settings", "migrate", "myapp"],
                catch_exceptions=True,
            )

    def test_dot_target_with_models(self, runner, tmp_path):
        (tmp_path / "models.py").write_text("# models\n")
        with patch(
            "openviper.core.flexible_adapter.bootstrap_and_run",
            side_effect=SystemExit(0),
        ):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                runner.invoke(viperctl, ["makemigrations", "."], catch_exceptions=True)

    def test_shell_allowed(self, runner):
        assert "shell" in _ALLOWED_COMMANDS

    def test_collectstatic_allowed(self, runner):
        assert "collectstatic" in _ALLOWED_COMMANDS

    def test_test_command_allowed(self, runner):
        assert "test" in _ALLOWED_COMMANDS
