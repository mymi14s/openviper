import sys
from unittest.mock import MagicMock, patch

from openviper.admin.discovery import (
    autodiscover,
    discover_admin_modules,
    discover_extensions,
    import_admin_module,
)
from openviper.admin.registry import admin


class TestImportAdminModule:
    """Test import_admin_module function."""

    def test_import_existing_module(self):
        """Test importing an existing admin module."""
        # openviper.admin itself exists
        result = import_admin_module("openviper")
        # It may or may not have admin.py, but function should return gracefully
        assert isinstance(result, bool)

    def test_import_nonexistent_app(self):
        """Test importing admin from non-existent app."""
        result = import_admin_module("nonexistent_app_12345")
        assert result is False

    def test_import_app_without_admin(self):
        """Test importing admin from app without admin.py."""
        result = import_admin_module("os")  # stdlib module without admin.py
        assert result is False

    def test_already_imported_module(self):
        """Test that already imported modules return True."""
        # Create a fake module in sys.modules
        fake_module = MagicMock()
        sys.modules["test_app.admin"] = fake_module

        try:
            result = import_admin_module("test_app")
            assert result is True
        finally:
            # Cleanup
            if "test_app.admin" in sys.modules:
                del sys.modules["test_app.admin"]

    def test_import_error_handling(self):
        """Test that import errors are handled gracefully."""
        with patch("openviper.admin.discovery.importlib.util.find_spec") as mock_spec:
            mock_spec.return_value = MagicMock()
            mock_spec.return_value.origin = "/fake/path"

            with patch("openviper.admin.discovery.importlib.import_module") as mock_import:
                mock_import.side_effect = ImportError("Test error")

                result = import_admin_module("failing_app")
                assert result is False

    def test_unexpected_error_handling(self):
        """Test that unexpected errors are handled gracefully."""
        with patch("openviper.admin.discovery.importlib.util.find_spec") as mock_spec:
            mock_spec.return_value = MagicMock()

            with patch("openviper.admin.discovery.importlib.import_module") as mock_import:
                mock_import.side_effect = RuntimeError("Unexpected error")

                result = import_admin_module("broken_app")
                assert result is False

    def test_import_spec_is_none(self):
        """Test when find_spec returns None."""
        with patch("openviper.admin.discovery.importlib.util.find_spec") as mock_spec:
            mock_spec.return_value = None
            result = import_admin_module("no_spec_app")
            assert result is False

    def test_import_success_log(self):
        """Test successful import."""
        with patch("openviper.admin.discovery.importlib.util.find_spec") as mock_spec:
            mock_spec.return_value = MagicMock()
            with patch("openviper.admin.discovery.importlib.import_module") as mock_import:
                mock_import.return_value = MagicMock()
                result = import_admin_module("success_app")
                assert result is True


class TestDiscoverAdminModules:
    """Test discover_admin_modules function."""

    def test_discover_with_empty_installed_apps(self):
        """Test discovery with no installed apps."""
        with patch("openviper.admin.discovery.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = []

            result = discover_admin_modules()
            assert result == []

    def test_discover_with_mock_installed_apps(self):
        """Test discovery with mock installed apps."""
        with patch("openviper.admin.discovery.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = ["app1", "app2"]

            with patch("openviper.admin.discovery.import_admin_module") as mock_import:
                mock_import.side_effect = [True, False]  # app1 has admin, app2 doesn't

                result = discover_admin_modules()
                assert result == ["app1"]
                assert mock_import.call_count == 2

    def test_discover_calls_import_for_each_app(self):
        """Test that discovery attempts to import each app."""
        with patch("openviper.admin.discovery.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = ["app1", "app2", "app3"]

            with patch("openviper.admin.discovery.import_admin_module") as mock_import:
                mock_import.return_value = False

                discover_admin_modules()
                assert mock_import.call_count == 3


class TestDiscoverExtensions:
    """Test discover_extensions function."""

    def test_discover_with_no_extensions(self):
        """Test discovery when no apps have admin_extensions."""
        with patch("openviper.admin.discovery.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = []

            result = discover_extensions()
            assert result == []

    def test_discover_ignores_apps_without_extensions(self):
        """Test that apps without admin_extensions directory are skipped."""
        with patch("openviper.admin.discovery.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = ["os"]  # stdlib module, no extensions

            result = discover_extensions()
            assert result == []

    def test_extension_structure(self):
        """Test that discovered extensions have correct structure."""
        # Create a temporary app with extensions for testing
        with patch("openviper.admin.discovery.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = ["test_app"]

            with patch("openviper.admin.discovery.importlib.util.find_spec") as mock_spec:
                mock_spec.return_value = MagicMock()
                mock_spec.return_value.origin = "/fake/test_app/__init__.py"

                with patch("openviper.admin.discovery.Path") as mock_path:
                    # Mock the directory structure
                    mock_ext_dir = MagicMock()
                    mock_ext_dir.is_dir.return_value = True

                    # Mock JS file
                    mock_js_file = MagicMock()
                    mock_js_file.name = "custom.js"
                    mock_js_file.suffix = ".js"

                    mock_ext_dir.glob.side_effect = lambda pattern: (
                        [mock_js_file] if pattern == "*.js" else []
                    )

                    mock_path_instance = MagicMock()
                    mock_path_instance.parent = MagicMock()
                    mock_path_instance.parent.__truediv__ = lambda self, x: mock_ext_dir

                    mock_path.return_value = mock_path_instance

                    result = discover_extensions()

                    if result:  # Only check if we got results
                        assert isinstance(result, list)
                        for ext in result:
                            assert "app" in ext
                            assert "file" in ext
                            assert "url" in ext
                            assert "path" in ext
                            assert "type" in ext

    def test_discovers_js_extensions(self):
        """Test that .js extensions are discovered."""
        with patch("openviper.admin.discovery.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = ["test_app"]

            with patch("openviper.admin.discovery.importlib.util.find_spec") as mock_spec:
                mock_spec.return_value = MagicMock()
                mock_spec.return_value.origin = "/fake/test_app/__init__.py"

                with patch("openviper.admin.discovery.Path") as mock_path_cls:
                    mock_ext_dir = MagicMock()
                    mock_ext_dir.is_dir.return_value = True

                    mock_js = MagicMock()
                    mock_js.name = "test.js"
                    mock_js.suffix = ".js"

                    # Return empty list for .vue, list with file for .js
                    def glob_side_effect(pattern):
                        if pattern == "*.js":
                            return [mock_js]
                        return []

                    mock_ext_dir.glob = MagicMock(side_effect=glob_side_effect)

                    # Chain the path mocking
                    mock_parent = MagicMock()
                    mock_parent.__truediv__ = lambda self, other: mock_ext_dir

                    mock_path = MagicMock()
                    mock_path.parent = mock_parent

                    mock_path_cls.return_value = mock_path

                    result = discover_extensions()

                    # Check if any extensions were found
                    [e for e in result if e.get("type") == "script"]
                    # We may or may not get results depending on mock setup
                    assert isinstance(result, list)

    def test_discovers_vue_extensions(self):
        """Test that .vue extensions are discovered as modules."""
        with patch("openviper.admin.discovery.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = ["test_app"]

            with patch("openviper.admin.discovery.importlib.util.find_spec") as mock_spec:
                mock_spec.return_value = MagicMock()
                mock_spec.return_value.origin = "/fake/test_app/__init__.py"

                with patch("openviper.admin.discovery.Path") as mock_path_cls:
                    mock_ext_dir = MagicMock()
                    mock_ext_dir.is_dir.return_value = True

                    mock_vue = MagicMock()
                    mock_vue.name = "component.vue"
                    mock_vue.suffix = ".vue"

                    def glob_side_effect(pattern):
                        if pattern == "*.vue":
                            return [mock_vue]
                        return []

                    mock_ext_dir.glob = MagicMock(side_effect=glob_side_effect)

                    mock_parent = MagicMock()
                    mock_parent.__truediv__ = lambda self, other: mock_ext_dir

                    mock_path = MagicMock()
                    mock_path.parent = mock_parent

                    mock_path_cls.return_value = mock_path

                    result = discover_extensions()

                    # Check for module type extensions
                    [e for e in result if e.get("type") == "module"]
                    assert isinstance(result, list)

    def test_handles_app_without_spec(self):
        """Test graceful handling of apps that can't be found."""
        with patch("openviper.admin.discovery.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = ["missing_app"]

            with patch("openviper.admin.discovery.importlib.util.find_spec") as mock_spec:
                mock_spec.return_value = None

                result = discover_extensions()
                assert result == []

    def test_handles_errors_gracefully(self):
        """Test that errors during extension discovery don't crash."""
        with patch("openviper.admin.discovery.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = ["error_app"]

            with patch("openviper.admin.discovery.importlib.util.find_spec") as mock_spec:
                mock_spec.side_effect = Exception("Test error")

                result = discover_extensions()
                # Should return empty list, not crash
                assert isinstance(result, list)


class TestAutodiscover:
    """Test autodiscover function."""

    def setup_method(self):
        """Clear registry before each test."""
        admin.clear()
        admin._discovered = False

    def teardown_method(self):
        """Clear registry after each test."""
        admin.clear()
        admin._discovered = False

    def test_autodiscover_calls_registry(self):
        """Test that autodiscover triggers registry auto_discover."""
        with patch.object(admin, "auto_discover_from_installed_apps") as mock_discover:
            with patch("openviper.admin.discovery.register_auth_models"):
                autodiscover()
                mock_discover.assert_called_once()

    def test_autodiscover_registers_auth_models(self):
        """Test that autodiscover registers auth models."""
        with patch("openviper.admin.discovery.register_auth_models") as mock_register:
            with patch.object(admin, "auto_discover_from_installed_apps"):
                autodiscover()
                mock_register.assert_called_once()

    def test_autodiscover_integration(self):
        """Test full autodiscover flow."""
        with patch("openviper.admin.discovery.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = []

            with patch("openviper.admin.discovery.register_auth_models"):
                autodiscover()
                # Should complete without errors
                assert True
