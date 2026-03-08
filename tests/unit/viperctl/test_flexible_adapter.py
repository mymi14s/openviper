"""Tests for openviper.core.flexible_adapter."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from openviper.conf.settings import Settings, _LazySettings
from openviper.core.flexible_adapter import (
    _ensure_models_imported,
    _ensure_sys_path,
    _inject_app_into_settings,
    _prepare_root_layout,
    _synthesize_settings_module,
    bootstrap_and_run,
)
from openviper.utils.module_resolver import ResolvedModule

_SYNTH_MODULE = "_viperctl_settings"


class TestEnsureSysPath:
    """Tests for _ensure_sys_path."""

    def test_adds_path_when_absent(self, tmp_path: Path) -> None:
        path_str = str(tmp_path / "unique_test_dir")
        original = sys.path.copy()
        try:
            assert path_str not in sys.path
            _ensure_sys_path(tmp_path / "unique_test_dir")
            assert path_str in sys.path
        finally:
            sys.path[:] = original

    def test_does_not_duplicate(self, tmp_path: Path) -> None:
        path_str = str(tmp_path)
        original = sys.path.copy()
        try:
            sys.path.insert(0, path_str)
            count_before = sys.path.count(path_str)
            _ensure_sys_path(tmp_path)
            assert sys.path.count(path_str) == count_before
        finally:
            sys.path[:] = original


class TestInjectAppIntoSettings:
    """Tests for _inject_app_into_settings."""

    def test_injects_new_app(self) -> None:
        """Adds an app to INSTALLED_APPS when not present."""
        lazy = _LazySettings()
        instance = Settings(INSTALLED_APPS=("existing_app",))
        object.__setattr__(lazy, "_instance", instance)
        object.__setattr__(lazy, "_configured", True)

        with patch("openviper.conf.settings.settings", lazy):
            _inject_app_into_settings("new_app")

        assert "new_app" in lazy.INSTALLED_APPS
        assert "existing_app" in lazy.INSTALLED_APPS

    def test_does_not_duplicate_existing_app(self) -> None:
        """Does not add an app that's already in INSTALLED_APPS."""
        lazy = _LazySettings()
        instance = Settings(INSTALLED_APPS=("myapp",))
        object.__setattr__(lazy, "_instance", instance)
        object.__setattr__(lazy, "_configured", True)

        apps_before = lazy.INSTALLED_APPS

        with patch("openviper.conf.settings.settings", lazy):
            _inject_app_into_settings("myapp")

        assert apps_before == lazy.INSTALLED_APPS


class TestSynthesizeSettingsModule:
    """Tests for _synthesize_settings_module."""

    def test_creates_importable_module(self) -> None:
        """The synthetic module is importable and contains a Settings subclass."""
        sys.modules.pop(_SYNTH_MODULE, None)
        try:
            module_name = _synthesize_settings_module()
            assert module_name == _SYNTH_MODULE
            assert module_name in sys.modules

            mod = sys.modules[module_name]
            klass = mod.__dict__["FlexibleSettings"]
            # Check by base class name to avoid identity issues across reloads.
            base_names = [c.__name__ for c in klass.__mro__]
            assert "Settings" in base_names
        finally:
            sys.modules.pop(_SYNTH_MODULE, None)

    def test_synthetic_settings_defaults(self) -> None:
        """The synthetic settings have reasonable defaults."""
        sys.modules.pop(_SYNTH_MODULE, None)
        try:
            module_name = _synthesize_settings_module()
            mod = sys.modules[module_name]
            klass = mod.__dict__["FlexibleSettings"]
            instance = klass()

            assert instance.PROJECT_NAME == "viperctl-project"
            assert instance.DEBUG is True
            assert "sqlite" in instance.DATABASE_URL
        finally:
            sys.modules.pop(_SYNTH_MODULE, None)


class TestEnsureModelsImported:
    """Tests for _ensure_models_imported."""

    def test_imports_module_models(self, tmp_path: Path) -> None:
        """Imports models from a module target."""
        todo = tmp_path / "todo_test_pkg"
        todo.mkdir()
        (todo / "__init__.py").write_text("")
        (todo / "models.py").write_text("LOADED = True\n")

        resolved = ResolvedModule(
            app_label="todo_test_pkg",
            app_path=todo,
            is_root=False,
            models_module="todo_test_pkg.models",
        )

        original_path = sys.path.copy()
        try:
            sys.path.insert(0, str(tmp_path))
            _ensure_models_imported(resolved)
            assert "todo_test_pkg.models" in sys.modules
            assert sys.modules["todo_test_pkg.models"].LOADED is True
        finally:
            sys.path[:] = original_path
            sys.modules.pop("todo_test_pkg.models", None)
            sys.modules.pop("todo_test_pkg", None)

    def test_root_layout_file_based_import(self, tmp_path: Path) -> None:
        """Loads root-level models.py via spec_from_file_location."""
        (tmp_path / "models.py").write_text("ROOT_LOADED = True\n")

        resolved = ResolvedModule(
            app_label="rootapp",
            app_path=tmp_path,
            is_root=True,
            models_module="rootapp.models",
        )

        original_path = sys.path.copy()
        try:
            _ensure_models_imported(resolved)
            assert "rootapp.models" in sys.modules
            assert sys.modules["rootapp.models"].ROOT_LOADED is True
        finally:
            sys.path[:] = original_path
            sys.modules.pop("rootapp.models", None)
            sys.modules.pop("models", None)

    def test_missing_models_file_no_error(self, tmp_path: Path) -> None:
        """Does not raise when models.py is missing (just logs)."""
        resolved = ResolvedModule(
            app_label="nomodels",
            app_path=tmp_path,
            is_root=True,
            models_module="nomodels.models",
        )
        # Should not raise
        _ensure_models_imported(resolved)

    def test_non_root_import_error_logs_and_returns(self, tmp_path: Path) -> None:

        resolved = ResolvedModule(
            app_label="myapp",
            app_path=tmp_path,
            is_root=False,
            models_module="myapp.models",
        )
        with patch(
            "openviper.core.flexible_adapter.importlib.import_module",
            side_effect=ImportError("no module"),
        ):
            # Must not raise; just logs at DEBUG level and returns early.
            _ensure_models_imported(resolved)


class TestPrepareRootLayout:
    """Tests for _prepare_root_layout."""

    def test_creates_init_py_when_absent(self, tmp_path: Path) -> None:

        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        assert not (app_dir / "__init__.py").exists()

        with patch("os.chdir"):  # avoid actually changing directories
            _prepare_root_layout(app_dir)

        assert (app_dir / "__init__.py").exists()

    def test_skips_existing_init_py(self, tmp_path: Path) -> None:

        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        init_py = app_dir / "__init__.py"
        init_py.write_text("# existing content")

        with patch("os.chdir"):
            _prepare_root_layout(app_dir)

        # File must still exist and contain the original content.
        assert init_py.read_text() == "# existing content"

    def test_adds_parent_to_sys_path(self, tmp_path: Path) -> None:

        app_dir = tmp_path / "myapp"
        app_dir.mkdir()

        original = sys.path.copy()
        try:
            with patch("os.chdir"):
                _prepare_root_layout(app_dir)
            assert str(tmp_path) in sys.path
        finally:
            sys.path[:] = original


class TestBootstrapAndRun:
    """Tests for bootstrap_and_run."""

    def test_non_root_with_explicit_settings(self, tmp_path: Path) -> None:

        resolved = ResolvedModule(
            app_label="myapp",
            app_path=tmp_path,
            is_root=False,
            models_module="myapp.models",
        )

        exec_calls = []

        def fake_exec(argv):
            exec_calls.append(argv)
            raise SystemExit(0)

        with (
            patch("openviper.core.flexible_adapter._ensure_sys_path"),
            patch("openviper.core.flexible_adapter._inject_app_into_settings"),
            patch("openviper.core.flexible_adapter._ensure_models_imported"),
            patch("openviper.setup"),
            patch(
                "openviper.core.management.execute_from_command_line",
                side_effect=fake_exec,
            ),
            patch.dict("os.environ", {}),
        ):
            with pytest.raises(SystemExit):
                bootstrap_and_run(
                    resolved=resolved,
                    settings_module="myapp.settings",
                    command="makemigrations",
                    command_args=(),
                )

        assert exec_calls == [["viperctl", "makemigrations"]]

    def test_syntheses_settings_when_none(self, tmp_path: Path) -> None:

        resolved = ResolvedModule(
            app_label="myapp",
            app_path=tmp_path,
            is_root=False,
            models_module="myapp.models",
        )

        captured_module = []

        def fake_exec(argv):
            captured_module.append(os.environ.get("OPENVIPER_SETTINGS_MODULE"))
            raise SystemExit(0)

        with (
            patch("openviper.core.flexible_adapter._ensure_sys_path"),
            patch("openviper.core.flexible_adapter._inject_app_into_settings"),
            patch("openviper.core.flexible_adapter._ensure_models_imported"),
            patch("openviper.setup"),
            patch(
                "openviper.core.management.execute_from_command_line",
                side_effect=fake_exec,
            ),
            patch("click.echo"),
            patch.dict("os.environ", {}),
        ):
            with pytest.raises(SystemExit):
                bootstrap_and_run(
                    resolved=resolved,
                    settings_module=None,  # triggers synthesis
                    command="migrate",
                    command_args=(),
                )

        # The synthetic module is named "_viperctl_settings"
        assert captured_module[0] == "_viperctl_settings"

    def test_root_layout_rewrites_bare_settings_module(self, tmp_path: Path) -> None:
        resolved = ResolvedModule(
            app_label="myapp",
            app_path=tmp_path,
            is_root=True,
            models_module="myapp.models",
        )
        captured_module = []

        def fake_exec(argv):
            captured_module.append(os.environ.get("OPENVIPER_SETTINGS_MODULE"))
            raise SystemExit(0)

        with (
            patch("openviper.core.flexible_adapter._prepare_root_layout"),
            patch("openviper.core.flexible_adapter._inject_app_into_settings"),
            patch("openviper.core.flexible_adapter._ensure_models_imported"),
            patch("openviper.setup"),
            patch(
                "openviper.core.management.execute_from_command_line",
                side_effect=fake_exec,
            ),
            patch.dict("os.environ", {}),
        ):
            with pytest.raises(SystemExit):
                bootstrap_and_run(
                    resolved=resolved,
                    settings_module="settings",  # bare name → gets rewritten
                    command="runserver",
                    command_args=(),
                )

        # "settings" is rewritten to "<app_label>.settings"
        assert captured_module[0] == "myapp.settings"
