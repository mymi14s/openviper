"""Tests for the OpenViper test scaffold command."""

from __future__ import annotations

from pathlib import Path

from openviper.core.management.commands.test import Command


def test_test_init_scaffolds_testing_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    command = Command()

    command.initialize_testing_files()

    assert (tmp_path / "tests" / "conftest.py").read_text(encoding="utf-8") == (
        'pytest_plugins = ["openviper.testing.plugin"]\n'
    )
    assert "async def test_health" in (tmp_path / "tests" / "test_health.py").read_text(
        encoding="utf-8"
    )
    assert "[tool.openviper.testing]" in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
