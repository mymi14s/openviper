"""Integration tests for admin discover_admin_modules / discover_extensions."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from openviper.admin.discovery import (
    autodiscover,
    discover_admin_modules,
    discover_extensions,
    import_admin_module,
)

# ---------------------------------------------------------------------------
# import_admin_module
# ---------------------------------------------------------------------------


def test_import_admin_module_already_loaded():
    """Returns True immediately when the module is already in sys.modules."""
    fake_mod = MagicMock()
    with patch.dict(sys.modules, {"myfakeapp.admin": fake_mod}):
        result = import_admin_module("myfakeapp")
    assert result is True


def test_import_admin_module_no_spec_returns_false():
    """Returns False when no admin.py is found for the app."""
    with patch("openviper.admin.discovery.importlib.util.find_spec", return_value=None):
        assert import_admin_module("nonexistent_app_xyz") is False


def test_import_admin_module_find_spec_raises_returns_false():
    """Returns False on ModuleNotFoundError from find_spec."""
    with patch(
        "openviper.admin.discovery.importlib.util.find_spec",
        side_effect=ModuleNotFoundError("nope"),
    ):
        assert import_admin_module("bad_app") is False


def test_import_admin_module_find_spec_raises_value_error():
    """Returns False on ValueError from find_spec (e.g. relative import)."""
    with patch(
        "openviper.admin.discovery.importlib.util.find_spec",
        side_effect=ValueError("bad"),
    ):
        assert import_admin_module("bad_app_v") is False


def test_import_admin_module_import_error_returns_false():
    """Returns False when importlib.import_module raises ImportError."""
    mock_spec = MagicMock()
    with (
        patch("openviper.admin.discovery.importlib.util.find_spec", return_value=mock_spec),
        patch(
            "openviper.admin.discovery.importlib.import_module",
            side_effect=ImportError("missing dep"),
        ),
    ):
        assert import_admin_module("broken_app") is False


def test_import_admin_module_unexpected_exception_returns_false():
    """Returns False on any other unexpected exception."""
    mock_spec = MagicMock()
    with (
        patch("openviper.admin.discovery.importlib.util.find_spec", return_value=mock_spec),
        patch(
            "openviper.admin.discovery.importlib.import_module",
            side_effect=RuntimeError("boom"),
        ),
    ):
        assert import_admin_module("crashing_app") is False


def test_import_admin_module_success():
    """Returns True when import_module succeeds."""
    mock_spec = MagicMock()
    with (
        patch("openviper.admin.discovery.importlib.util.find_spec", return_value=mock_spec),
        patch("openviper.admin.discovery.importlib.import_module"),
    ):
        assert import_admin_module("good_app") is True


# ---------------------------------------------------------------------------
# discover_admin_modules
# ---------------------------------------------------------------------------


def test_discover_admin_modules_processes_installed_apps():
    """Calls import_admin_module for every entry in INSTALLED_APPS."""
    with patch("openviper.admin.discovery.settings") as ms:
        ms.INSTALLED_APPS = ["app_a", "app_b", "app_c"]
        with patch(
            "openviper.admin.discovery.import_admin_module",
            side_effect=[True, False, True],
        ) as mock_import:
            result = discover_admin_modules()

    assert mock_import.call_count == 3
    assert result == ["app_a", "app_c"]


def test_discover_admin_modules_empty_returns_empty():
    with patch("openviper.admin.discovery.settings") as ms:
        ms.INSTALLED_APPS = []
        result = discover_admin_modules()
    assert result == []


# ---------------------------------------------------------------------------
# discover_extensions
# ---------------------------------------------------------------------------


def test_discover_extensions_finds_js_and_vue_files():
    """Returns extension entries for .js and .vue files in admin_extensions/."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ext_dir = Path(tmpdir) / "admin_extensions"
        ext_dir.mkdir()
        (ext_dir / "widget.js").write_text("// js")
        (ext_dir / "fancy.vue").write_text("<template/>")

        mock_spec = MagicMock()
        mock_spec.origin = str(Path(tmpdir) / "__init__.py")

        with patch("openviper.admin.discovery.settings") as ms:
            ms.INSTALLED_APPS = ["myapp"]
            with patch(
                "openviper.admin.discovery.importlib.util.find_spec",
                return_value=mock_spec,
            ):
                result = discover_extensions()

    assert len(result) == 2
    file_names = {e["file"] for e in result}
    assert "widget.js" in file_names
    assert "fancy.vue" in file_names
    types = {e["file"]: e["type"] for e in result}
    assert types["widget.js"] == "script"
    assert types["fancy.vue"] == "module"


def test_discover_extensions_no_ext_dir_returns_empty():
    """Returns empty list when app has no admin_extensions dir."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mock_spec = MagicMock()
        mock_spec.origin = str(Path(tmpdir) / "__init__.py")

        with patch("openviper.admin.discovery.settings") as ms:
            ms.INSTALLED_APPS = ["noextapp"]
            with patch(
                "openviper.admin.discovery.importlib.util.find_spec",
                return_value=mock_spec,
            ):
                result = discover_extensions()

    assert result == []


def test_discover_extensions_none_spec_skipped():
    """Apps whose spec is None are silently skipped."""
    with patch("openviper.admin.discovery.settings") as ms:
        ms.INSTALLED_APPS = ["ghostapp"]
        with patch(
            "openviper.admin.discovery.importlib.util.find_spec",
            return_value=None,
        ):
            result = discover_extensions()
    assert result == []


def test_discover_extensions_exception_silently_skipped():
    """Exceptions during extension scan are swallowed."""
    with patch("openviper.admin.discovery.settings") as ms:
        ms.INSTALLED_APPS = ["crashapp"]
        with patch(
            "openviper.admin.discovery.importlib.util.find_spec",
            side_effect=RuntimeError("boom"),
        ):
            result = discover_extensions()
    assert result == []


# ---------------------------------------------------------------------------
# autodiscover
# ---------------------------------------------------------------------------


def test_autodiscover_calls_auto_discover_and_register_auth():
    with (
        patch("openviper.admin.discovery.admin") as mock_admin,
        patch("openviper.admin.discovery.register_auth_models") as mock_reg,
    ):
        autodiscover()

    mock_admin.auto_discover_from_installed_apps.assert_called_once()
    mock_reg.assert_called_once()
