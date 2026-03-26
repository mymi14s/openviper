"""Unit tests for :mod:`openviper.utils.settings_discovery`."""

from __future__ import annotations

from pathlib import Path

from openviper.utils.settings_discovery import discover_settings_module


class TestDiscoverSettingsModule:
    def test_explicit_wins(self, tmp_path: Path) -> None:
        assert (
            discover_settings_module("proj", cwd=tmp_path, explicit="custom.settings")
            == "custom.settings"
        )

    def test_module_settings_found(self, tmp_path: Path) -> None:
        module_dir = tmp_path / "proj"
        module_dir.mkdir()
        (module_dir / "settings.py").write_text("x = 1\n")
        assert discover_settings_module("proj", cwd=tmp_path) == "proj.settings"

    def test_root_settings_found(self, tmp_path: Path) -> None:
        (tmp_path / "settings.py").write_text("x = 1\n")
        assert discover_settings_module(".", cwd=tmp_path) == "settings"

    def test_none_when_missing(self, tmp_path: Path) -> None:
        assert discover_settings_module("proj", cwd=tmp_path) is None
