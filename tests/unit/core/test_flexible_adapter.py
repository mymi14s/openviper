"""Unit tests for openviper.core.flexible_adapter — viperctl environment bootstrap."""

import dataclasses
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from openviper.core.flexible_adapter import (
    _ensure_models_imported,
    _ensure_sys_path,
    _inject_app_into_settings,
    _prepare_root_layout,
    _synthesize_settings_module,
    bootstrap_and_run,
)


@pytest.fixture
def mock_resolved():
    """Create a mock ResolvedModule object."""
    resolved = Mock()
    resolved.app_label = "testapp"
    resolved.app_path = Path("/fake/testapp")
    resolved.models_module = "testapp.models"
    resolved.is_root = False
    return resolved


@pytest.fixture
def mock_root_resolved():
    """Create a mock ResolvedModule for root layout."""
    resolved = Mock()
    resolved.app_label = "rootapp"
    resolved.app_path = Path("/fake/rootapp")
    resolved.models_module = "rootapp.models"
    resolved.is_root = True
    return resolved


class TestEnsureSysPath:
    """Test _ensure_sys_path function."""

    def test_ensure_sys_path_adds_new_path(self):
        test_path = Path("/unique/test/path")
        original_sys_path = sys.path.copy()

        try:
            _ensure_sys_path(test_path)
            assert str(test_path) in sys.path
            assert sys.path.index(str(test_path)) == 0  # Should be first
        finally:
            sys.path[:] = original_sys_path

    def test_ensure_sys_path_does_not_duplicate(self):
        test_path = Path("/duplicate/test/path")
        original_sys_path = sys.path.copy()

        try:
            sys.path.insert(0, str(test_path))
            initial_count = sys.path.count(str(test_path))

            _ensure_sys_path(test_path)

            assert sys.path.count(str(test_path)) == initial_count
        finally:
            sys.path[:] = original_sys_path


class TestPrepareRootLayout:
    """Test _prepare_root_layout function."""

    def test_prepare_root_layout_creates_init_py(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            original_cwd = os.getcwd()

            try:
                os.chdir(tmpdir_path)
                _prepare_root_layout(tmpdir_path)

                init_file = tmpdir_path / "__init__.py"
                assert init_file.exists()
            finally:
                os.chdir(original_cwd)

    def test_prepare_root_layout_existing_init_py(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            init_file = tmpdir_path / "__init__.py"
            init_file.write_text("# existing")

            original_cwd = os.getcwd()

            try:
                os.chdir(tmpdir_path)
                _prepare_root_layout(tmpdir_path)

                # Should not overwrite
                assert init_file.read_text() == "# existing"
            finally:
                os.chdir(original_cwd)

    def test_prepare_root_layout_changes_cwd(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            original_cwd = os.getcwd()

            try:
                os.chdir(tmpdir_path)
                _prepare_root_layout(tmpdir_path)

                # Should have changed to parent (use realpath for symlink resolution)
                assert os.path.realpath(os.getcwd()) == os.path.realpath(str(tmpdir_path.parent))
            finally:
                os.chdir(original_cwd)

    def test_prepare_root_layout_adds_parent_to_sys_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            original_cwd = os.getcwd()
            original_sys_path = sys.path.copy()

            try:
                os.chdir(tmpdir_path)
                _prepare_root_layout(tmpdir_path)

                assert str(tmpdir_path.parent) in sys.path
            finally:
                os.chdir(original_cwd)
                sys.path[:] = original_sys_path


class TestInjectAppIntoSettings:
    """Test _inject_app_into_settings function."""

    def test_inject_app_into_settings_new_app(self):
        """Test injecting a new app into settings."""
        # Create a custom class that mimics the LazySettings behavior
        # object.__getattribute__ is used to access _instance directly
        mock_instance = Mock()
        mock_instance.INSTALLED_APPS = ("existing_app",)

        class MockLazySettings:
            def __init__(self):
                # Set _instance directly so object.__getattribute__ finds it
                object.__setattr__(self, "_instance", mock_instance)
                self.INSTALLED_APPS = ("existing_app",)

        mock_lazy = MockLazySettings()

        with patch("openviper.core.flexible_adapter._lazy", mock_lazy):
            with patch("openviper.core.flexible_adapter.dataclasses.replace") as mock_replace:
                new_instance = Mock()
                new_instance.INSTALLED_APPS = ("new_app", "existing_app")
                mock_replace.return_value = new_instance

                _inject_app_into_settings("new_app")

                mock_replace.assert_called_once()
                # Verify the new INSTALLED_APPS includes the new app
                call_kwargs = mock_replace.call_args[1]
                assert "INSTALLED_APPS" in call_kwargs
                assert call_kwargs["INSTALLED_APPS"][0] == "new_app"

    def test_inject_app_into_settings_existing_app(self):
        """Test that existing apps are not duplicated."""
        mock_lazy = Mock()
        mock_lazy.INSTALLED_APPS = ("existing_app",)

        with patch("openviper.core.flexible_adapter._lazy", mock_lazy):
            with patch("openviper.core.flexible_adapter.dataclasses.replace") as mock_replace:
                _inject_app_into_settings("existing_app")

                # Should not call replace if app already exists
                mock_replace.assert_not_called()


class TestEnsureModelsImported:
    """Test _ensure_models_imported function."""

    def test_ensure_models_imported_success(self, mock_resolved):
        with patch("importlib.import_module") as mock_import:
            _ensure_models_imported(mock_resolved)

            mock_import.assert_called_once_with("testapp.models")

    def test_ensure_models_imported_import_error_non_root(self, mock_resolved):
        mock_resolved.is_root = False

        with patch("importlib.import_module", side_effect=ImportError):
            # Should not raise, just log
            _ensure_models_imported(mock_resolved)

    def test_ensure_models_imported_root_layout_file_exists(self, mock_root_resolved):
        with tempfile.TemporaryDirectory() as tmpdir:
            app_path = Path(tmpdir) / "rootapp"
            app_path.mkdir()
            models_file = app_path / "models.py"
            models_file.write_text("# models")

            mock_root_resolved.app_path = app_path

            original_sys_modules = sys.modules.copy()

            try:
                with patch("importlib.import_module", side_effect=ImportError):
                    _ensure_models_imported(mock_root_resolved)

                    # Should have loaded via spec
                    assert "rootapp.models" in sys.modules
            finally:
                sys.modules.clear()
                sys.modules.update(original_sys_modules)

    def test_ensure_models_imported_root_layout_no_file(self, mock_root_resolved):
        with tempfile.TemporaryDirectory() as tmpdir:
            app_path = Path(tmpdir) / "rootapp"
            app_path.mkdir()

            mock_root_resolved.app_path = app_path

            with patch("importlib.import_module", side_effect=ImportError):
                # Should not raise error
                _ensure_models_imported(mock_root_resolved)


class TestSynthesizeSettingsModule:
    """Test _synthesize_settings_module function."""

    def test_synthesize_settings_module_creates_module(self):
        original_sys_modules = sys.modules.copy()

        try:
            module_name = _synthesize_settings_module()

            assert module_name == "_viperctl_settings"
            assert "_viperctl_settings" in sys.modules

            module = sys.modules["_viperctl_settings"]
            assert hasattr(module, "FlexibleSettings")

            # Test FlexibleSettings attributes
            settings_cls = module.FlexibleSettings
            instance = settings_cls()
            assert instance.PROJECT_NAME == "viperctl-project"
            assert instance.DEBUG is True
            assert instance.DATABASE_URL == "sqlite+aiosqlite:///db.sqlite3"
            assert instance.INSTALLED_APPS == ()
        finally:
            sys.modules.clear()
            sys.modules.update(original_sys_modules)

    def test_synthesize_settings_module_frozen_dataclass(self):
        original_sys_modules = sys.modules.copy()

        try:
            module_name = _synthesize_settings_module()
            module = sys.modules[module_name]
            settings_cls = module.FlexibleSettings

            # Test that it's a frozen dataclass
            assert dataclasses.is_dataclass(settings_cls)

            instance = settings_cls()
            with pytest.raises(dataclasses.FrozenInstanceError):
                instance.DEBUG = False
        finally:
            sys.modules.clear()
            sys.modules.update(original_sys_modules)


class TestBootstrapAndRun:
    """Test bootstrap_and_run function."""

    @patch("openviper.core.flexible_adapter.execute_from_command_line")
    @patch("openviper.core.flexible_adapter._inject_app_into_settings")
    @patch("openviper.core.flexible_adapter._ensure_models_imported")
    @patch("openviper.core.flexible_adapter._ensure_sys_path")
    def test_bootstrap_and_run_standard_layout(
        self,
        mock_ensure_path,
        mock_ensure_models,
        mock_inject,
        mock_execute,
        mock_resolved,
    ):
        mock_resolved.is_root = False

        with patch("openviper.setup") as mock_setup:
            with patch("sys.exit"):
                bootstrap_and_run(
                    resolved=mock_resolved,
                    settings_module="myproject.settings",
                    command="migrate",
                    command_args=("--fake",),
                )

        mock_ensure_path.assert_called_once()
        mock_setup.assert_called_once_with(force=True)
        mock_inject.assert_called_once_with("testapp")
        mock_ensure_models.assert_called_once_with(mock_resolved)
        mock_execute.assert_called_once_with(["viperctl", "migrate", "--fake"])

        assert os.environ["OPENVIPER_SETTINGS_MODULE"] == "myproject.settings"

    @patch("openviper.core.flexible_adapter.execute_from_command_line")
    @patch("openviper.core.flexible_adapter._inject_app_into_settings")
    @patch("openviper.core.flexible_adapter._ensure_models_imported")
    @patch("openviper.core.flexible_adapter._prepare_root_layout")
    def test_bootstrap_and_run_root_layout(
        self,
        mock_prepare,
        mock_ensure_models,
        mock_inject,
        mock_execute,
        mock_root_resolved,
    ):
        mock_root_resolved.is_root = True

        with patch("openviper.setup") as mock_setup:
            with patch("sys.exit"):
                bootstrap_and_run(
                    resolved=mock_root_resolved,
                    settings_module="settings",
                    command="runserver",
                    command_args=(),
                )

        mock_prepare.assert_called_once()
        mock_setup.assert_called_once_with(force=True)

        # For root layout, settings should be rewritten
        assert os.environ["OPENVIPER_SETTINGS_MODULE"] == "rootapp.settings"

    @patch("openviper.core.flexible_adapter.execute_from_command_line")
    @patch("openviper.core.flexible_adapter._inject_app_into_settings")
    @patch("openviper.core.flexible_adapter._ensure_models_imported")
    @patch("openviper.core.flexible_adapter._ensure_sys_path")
    @patch("openviper.core.flexible_adapter._synthesize_settings_module")
    @patch("openviper.core.flexible_adapter.click.echo")
    def test_bootstrap_and_run_no_settings_module(
        self,
        mock_echo,
        mock_synthesize,
        mock_ensure_path,
        mock_ensure_models,
        mock_inject,
        mock_execute,
        mock_resolved,
    ):
        mock_synthesize.return_value = "_viperctl_settings"

        with patch("openviper.setup"):
            with patch("sys.exit"):
                bootstrap_and_run(
                    resolved=mock_resolved,
                    settings_module=None,
                    command="shell",
                    command_args=(),
                )

        mock_synthesize.assert_called_once()
        mock_echo.assert_called_once_with(
            "Warning: No settings.py found; using default settings.",
            err=True,
        )
        assert os.environ["OPENVIPER_SETTINGS_MODULE"] == "_viperctl_settings"

    @patch("openviper.core.flexible_adapter.execute_from_command_line")
    @patch("openviper.core.flexible_adapter._inject_app_into_settings")
    @patch("openviper.core.flexible_adapter._ensure_models_imported")
    @patch("openviper.core.flexible_adapter._ensure_sys_path")
    def test_bootstrap_and_run_with_command_args(
        self,
        mock_ensure_path,
        mock_ensure_models,
        mock_inject,
        mock_execute,
        mock_resolved,
    ):
        with patch("openviper.setup"):
            with patch("sys.exit"):
                bootstrap_and_run(
                    resolved=mock_resolved,
                    settings_module="settings",
                    command="test",
                    command_args=("tests/", "-v", "--failfast"),
                )

        mock_execute.assert_called_once_with(["viperctl", "test", "tests/", "-v", "--failfast"])

    @patch("openviper.core.flexible_adapter.execute_from_command_line")
    @patch("openviper.core.flexible_adapter._inject_app_into_settings")
    @patch("openviper.core.flexible_adapter._ensure_models_imported")
    @patch("openviper.core.flexible_adapter._prepare_root_layout")
    def test_bootstrap_and_run_root_layout_settings_not_bare(
        self,
        mock_prepare,
        mock_ensure_models,
        mock_inject,
        mock_execute,
        mock_root_resolved,
    ):
        """Test that non-bare settings names are not rewritten."""
        mock_root_resolved.is_root = True

        with patch("openviper.setup"):
            with patch("sys.exit"):
                bootstrap_and_run(
                    resolved=mock_root_resolved,
                    settings_module="myproject.settings",
                    command="migrate",
                    command_args=(),
                )

        # Should not be rewritten
        assert os.environ["OPENVIPER_SETTINGS_MODULE"] == "myproject.settings"


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_ensure_sys_path_with_str_path(self):
        """Test that _ensure_sys_path handles string paths."""
        test_path = "/test/string/path"
        original_sys_path = sys.path.copy()

        try:
            _ensure_sys_path(Path(test_path))
            assert test_path in sys.path
        finally:
            sys.path[:] = original_sys_path

    def test_inject_app_tuple_conversion(self):
        """Test that INSTALLED_APPS list is handled correctly."""
        # Create mock settings with a list INSTALLED_APPS
        mock_instance = Mock()
        mock_instance.INSTALLED_APPS = ["list_app"]

        class MockLazySettings:
            def __init__(self):
                # Set _instance directly so object.__getattribute__ finds it
                object.__setattr__(self, "_instance", mock_instance)
                self.INSTALLED_APPS = ["list_app"]

        mock_lazy = MockLazySettings()

        with patch("openviper.core.flexible_adapter._lazy", mock_lazy):
            with patch("openviper.core.flexible_adapter.dataclasses.replace") as mock_replace:
                new_instance = Mock()
                mock_replace.return_value = new_instance

                _inject_app_into_settings("new_app")

                # Verify replace was called
                mock_replace.assert_called_once()
                # Verify the new INSTALLED_APPS includes the new app
                call_kwargs = mock_replace.call_args[1]
                assert "INSTALLED_APPS" in call_kwargs
                # The INSTALLED_APPS should be a tuple with new_app first
                assert call_kwargs["INSTALLED_APPS"][0] == "new_app"
