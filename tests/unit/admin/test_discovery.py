import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openviper.admin import discovery
from openviper.admin.discovery import (
    autodiscover,
    discover_admin_modules,
    discover_extensions,
    import_admin_module,
)


def test_discover_admin_modules():
    with patch("openviper.admin.discovery.settings") as mock_settings:
        mock_settings.INSTALLED_APPS = ["app1", "app2"]
        with patch("openviper.admin.discovery.import_admin_module") as mock_import:
            mock_import.side_effect = [True, False]
            discovered = discover_admin_modules()
            assert discovered == ["app1"]
            assert mock_import.call_count == 2


def test_import_admin_module_already_loaded():
    app_name = "test_app"
    admin_module_name = f"{app_name}.admin"
    with patch.dict(sys.modules, {admin_module_name: MagicMock()}):
        assert import_admin_module(app_name) is True


def test_import_admin_module_not_found():
    with patch("importlib.util.find_spec", return_value=None):
        assert import_admin_module("missing_app") is False


def test_import_admin_module_find_spec_error():
    with patch("importlib.util.find_spec", side_effect=ValueError("Invalid module")):
        assert import_admin_module("bad_app") is False


def test_import_admin_module_success():
    with patch("importlib.util.find_spec") as mock_find_spec:
        mock_find_spec.return_value = MagicMock()
        with patch("importlib.import_module") as mock_import_module:
            assert import_admin_module("good_app") is True
            mock_import_module.assert_called_once_with("good_app.admin")


def test_import_admin_module_import_error():
    with patch("importlib.util.find_spec") as mock_find_spec:
        mock_find_spec.return_value = MagicMock()
        with patch("importlib.import_module", side_effect=ImportError("Import failed")):
            assert import_admin_module("broken_app") is False


def test_import_admin_module_unexpected_error():
    with patch("importlib.util.find_spec") as mock_find_spec:
        mock_find_spec.return_value = MagicMock()
        with patch("importlib.import_module", side_effect=Exception("Unexpected")):
            assert import_admin_module("weird_app") is False


def test_discover_extensions(tmp_path):
    with patch("openviper.admin.discovery.settings") as mock_settings:
        mock_settings.INSTALLED_APPS = ["app1", "app2", "app3"]

        # Create temp dir structure
        app1_dir = tmp_path / "app1"
        app1_dir.mkdir()
        app1_ext = app1_dir / "admin_extensions"
        app1_ext.mkdir()
        (app1_ext / "plugin.js").write_text("console.log('js');")
        (app1_ext / "component.vue").write_text("<template></template>")

        app2_dir = tmp_path / "app2"
        app2_dir.mkdir()

        def mock_find_spec(app_name):
            if app_name == "app1":
                spec = MagicMock()
                spec.origin = str(app1_dir / "__init__.py")
                return spec
            elif app_name == "app2":
                spec = MagicMock()
                spec.origin = str(app2_dir / "__init__.py")
                return spec
            elif app_name == "app3":
                return None
            return None

        with patch("importlib.util.find_spec", side_effect=mock_find_spec):
            extensions = discover_extensions()
            assert len(extensions) == 2

            # They might be returned in order of glob
            ext_names = [e["file"] for e in extensions]
            assert "plugin.js" in ext_names
            assert "component.vue" in ext_names

            for e in extensions:
                assert e["app"] == "app1"
                assert "/admin/extensions/app1/" in e["url"]
                if e["file"].endswith(".vue"):
                    assert e["type"] == "module"
                else:
                    assert e["type"] == "script"


def test_discover_extensions_exception():
    with patch("openviper.admin.discovery.settings") as mock_settings:
        mock_settings.INSTALLED_APPS = ["app_err"]
        with patch("importlib.util.find_spec", side_effect=Exception("Some error")):
            extensions = discover_extensions()
            assert extensions == []


def test_autodiscover():
    with patch("openviper.admin.discovery.admin.auto_discover_from_installed_apps") as mock_auto:
        with patch("openviper.admin.discovery.register_auth_models") as mock_register:
            autodiscover()
            mock_auto.assert_called_once()
            mock_register.assert_called_once()
