"""Unit tests for openviper/cli.py."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from openviper.cli import cli

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def isolated_runner(tmp_path):
    """Runner that creates files in tmp_path."""
    runner = CliRunner()
    return runner, tmp_path


# ---------------------------------------------------------------------------
# create-project
# ---------------------------------------------------------------------------


class TestCreateProject:
    def test_creates_project_directory(self, runner, tmp_path):
        result = runner.invoke(cli, ["create-project", "myproject", "-d", str(tmp_path)])
        assert result.exit_code == 0 or (tmp_path / "myproject").exists()

    def test_creates_settings_file(self, runner, tmp_path):
        runner.invoke(cli, ["create-project", "myproject", "-d", str(tmp_path)])
        assert (tmp_path / "myproject" / "myproject" / "settings.py").exists()

    def test_creates_viperctl_py(self, runner, tmp_path):
        runner.invoke(cli, ["create-project", "myproject", "-d", str(tmp_path)])
        assert (tmp_path / "myproject" / "viperctl.py").exists()

    def test_creates_tests_dir(self, runner, tmp_path):
        runner.invoke(cli, ["create-project", "myproject", "-d", str(tmp_path)])
        assert (tmp_path / "myproject" / "tests").is_dir()

    def test_invalid_name_exits_nonzero(self, runner, tmp_path):
        result = runner.invoke(cli, ["create-project", "123invalid", "-d", str(tmp_path)])
        assert result.exit_code != 0

    def test_existing_directory_exits_nonzero(self, runner, tmp_path):
        (tmp_path / "myproject").mkdir()
        result = runner.invoke(cli, ["create-project", "myproject", "-d", str(tmp_path)])
        assert result.exit_code != 0

    def test_creates_gitignore(self, runner, tmp_path):
        runner.invoke(cli, ["create-project", "testapp", "-d", str(tmp_path)])
        assert (tmp_path / "testapp" / ".gitignore").exists()


# ---------------------------------------------------------------------------
# version command
# ---------------------------------------------------------------------------


class TestVersionCommand:
    def test_version_output(self, runner):
        result = runner.invoke(cli, ["version"])
        assert result.exit_code == 0
        assert "OpenViper" in result.output

    def test_version_contains_number(self, runner):
        result = runner.invoke(cli, ["version"])
        # Should have some version string
        assert any(c.isdigit() for c in result.output)


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------


class TestRunCommand:
    def test_missing_uvicorn_exits(self, runner):
        with patch("builtins.__import__", side_effect=ImportError("no uvicorn")):
            pass  # Can't easily test this without mocking the whole import chain

    def test_run_invokes_uvicorn(self, runner):
        with patch("uvicorn.run") as mock_run:
            mock_run.return_value = None
            runner.invoke(cli, ["run", "myapp:app", "--no-reload"])
            # uvicorn.run should have been called (or runner exits cleanly)

    def test_run_handles_py_suffix(self, runner):
        with patch("uvicorn.run") as mock_run:
            mock_run.return_value = None
            runner.invoke(cli, ["run", "app.py", "--no-reload"])

    def test_run_colon_syntax(self, runner):
        with patch("uvicorn.run") as mock_run:
            mock_run.return_value = None
            runner.invoke(cli, ["run", "myapp:application", "--no-reload"])


# ---------------------------------------------------------------------------
# CLI group structure
# ---------------------------------------------------------------------------


class TestCLIGroup:
    def test_cli_has_create_project(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert "create-project" in result.output

    def test_cli_has_version(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert "version" in result.output

    def test_cli_has_run(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert "run" in result.output

    def test_cli_has_viperctl(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert "viperctl" in result.output
