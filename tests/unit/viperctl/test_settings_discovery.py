"""Tests for openviper.utils.settings_discovery."""

from __future__ import annotations

from pathlib import Path

from openviper.utils.settings_discovery import discover_settings_module


class TestDiscoverSettingsModule:
    """Tests for discover_settings_module()."""

    def test_explicit_flag_takes_priority(self, tmp_path: Path) -> None:
        """--settings value is returned verbatim regardless of filesystem."""
        result = discover_settings_module(
            target=".",
            cwd=tmp_path,
            explicit="custom.settings",
        )
        assert result == "custom.settings"

    def test_explicit_flag_over_existing_files(self, tmp_path: Path) -> None:
        """--settings wins even when settings.py exists on disk."""
        (tmp_path / "settings.py").write_text("# root settings\n")
        result = discover_settings_module(
            target=".",
            cwd=tmp_path,
            explicit="override.settings",
        )
        assert result == "override.settings"

    def test_module_settings_detected(self, tmp_path: Path) -> None:
        """<target>/settings.py is found when target is a module name."""
        todo = tmp_path / "todo"
        todo.mkdir()
        (todo / "settings.py").write_text("# todo settings\n")

        result = discover_settings_module(target="todo", cwd=tmp_path)
        assert result == "todo.settings"

    def test_module_settings_over_root(self, tmp_path: Path) -> None:
        """Module settings take priority over root settings."""
        (tmp_path / "settings.py").write_text("# root settings\n")
        todo = tmp_path / "todo"
        todo.mkdir()
        (todo / "settings.py").write_text("# todo settings\n")

        result = discover_settings_module(target="todo", cwd=tmp_path)
        assert result == "todo.settings"

    def test_root_settings_detected(self, tmp_path: Path) -> None:
        """settings.py at CWD root is detected for '.' target."""
        (tmp_path / "settings.py").write_text("# root settings\n")

        result = discover_settings_module(target=".", cwd=tmp_path)
        assert result == "settings"

    def test_root_settings_for_module_without_own_settings(
        self,
        tmp_path: Path,
    ) -> None:
        """Falls back to root settings when module has no settings.py."""
        (tmp_path / "settings.py").write_text("# root settings\n")
        todo = tmp_path / "todo"
        todo.mkdir()
        # todo/ exists but has no settings.py

        result = discover_settings_module(target="todo", cwd=tmp_path)
        assert result == "settings"

    def test_no_settings_found(self, tmp_path: Path) -> None:
        """Returns None when no settings.py exists anywhere."""
        result = discover_settings_module(target=".", cwd=tmp_path)
        assert result is None

    def test_no_settings_for_module_target(self, tmp_path: Path) -> None:
        """Returns None when neither module nor root has settings.py."""
        todo = tmp_path / "todo"
        todo.mkdir()

        result = discover_settings_module(target="todo", cwd=tmp_path)
        assert result is None

    def test_defaults_to_cwd(self) -> None:
        """When cwd is not provided, defaults to Path.cwd()."""
        # This should not raise; we just verify it runs.
        result = discover_settings_module(target="nonexistent_module_xyz")
        # Result depends on CWD contents, but should be str or None.
        assert result is None or isinstance(result, str)

    def test_dot_target_skips_module_check(self, tmp_path: Path) -> None:
        """Target '.' does not look for './' as a module path."""
        (tmp_path / "settings.py").write_text("# root\n")
        result = discover_settings_module(target=".", cwd=tmp_path)
        assert result == "settings"
