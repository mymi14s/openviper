"""Unit tests for openviper.template.paths - shared path utilities."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

import openviper.template.paths as paths_mod
from openviper.template.paths import (
    get_app_dir,
    iter_app_dirs,
    validate_path_and_warn,
    validate_path_within_root,
)


class TestGetAppDir:
    def test_returns_directory_for_importable_app(self):
        mock_mod = MagicMock()
        mock_mod.__file__ = "/srv/apps/myapp/__init__.py"
        with patch("openviper.template.paths.importlib.import_module", return_value=mock_mod):
            result = get_app_dir("myapp")
        assert result == "/srv/apps/myapp"

    def test_returns_none_on_import_error(self):
        with patch("openviper.template.paths.importlib.import_module", side_effect=ImportError):
            result = get_app_dir("nonexistent_app")
        assert result is None

    def test_returns_none_on_attribute_error(self):
        with patch(
            "openviper.template.paths.importlib.import_module",
            side_effect=AttributeError,
        ):
            result = get_app_dir("broken_app")
        assert result is None

    def test_returns_none_when_module_lacks_file(self):
        mock_mod = MagicMock(spec=[])
        with patch("openviper.template.paths.importlib.import_module", return_value=mock_mod):
            result = get_app_dir("namespace_pkg")
        assert result is None

    def test_returns_none_when_file_is_none(self):
        mock_mod = MagicMock()
        mock_mod.__file__ = None
        with patch("openviper.template.paths.importlib.import_module", return_value=mock_mod):
            result = get_app_dir("myapp")
        assert result is None


class TestValidatePathWithinRoot:
    def test_allows_path_within_root(self):
        result = validate_path_within_root("/project/templates", "/project")
        assert result is not None

    def test_allows_exact_root(self):
        result = validate_path_within_root("/project", "/project")
        assert result is not None

    def test_rejects_path_escaping_root(self):
        result = validate_path_within_root("/etc/passwd", "/project")
        assert result is None

    def test_rejects_traversal_attack(self):
        result = validate_path_within_root("/project/../../etc/passwd", "/project")
        assert result is None

    def test_rejects_unrelated_path(self):
        result = validate_path_within_root("/other/dir", "/project")
        assert result is None


class TestValidatePathAndWarn:
    def test_returns_validated_path_when_within_root(self):
        result = validate_path_and_warn("/project/templates", "/project", "Test")
        assert result is not None

    def test_returns_none_and_warns_when_escaping_root(self, caplog):
        result = validate_path_and_warn("/etc/passwd", "/project", "Test label")
        assert result is None
        assert any("Test label" in r.message for r in caplog.records)

    def test_includes_path_in_warning_message(self, caplog):
        validate_path_and_warn("/etc/passwd", "/project", "MyLabel")
        messages = [r.message for r in caplog.records]
        assert any("/etc/passwd" in m for m in messages)


class TestIterAppDirs:
    def test_yields_resolvable_apps(self):
        mock_mod = MagicMock()
        mock_mod.__file__ = "/srv/apps/blog/__init__.py"
        with patch("openviper.template.paths.get_app_dir", return_value="/srv/apps/blog"):
            with patch("openviper.template.paths.settings") as s:
                s.INSTALLED_APPS = ("blog",)
                result = list(iter_app_dirs())
        assert len(result) == 1
        assert result[0] == ("blog", "/srv/apps/blog")

    def test_skips_unresolvable_apps(self):
        with patch("openviper.template.paths.get_app_dir", return_value=None):
            with patch("openviper.template.paths.settings") as s:
                s.INSTALLED_APPS = ("missing_app",)
                result = list(iter_app_dirs())
        assert result == []

    def test_yields_multiple_apps(self):
        with patch(
            "openviper.template.paths.get_app_dir",
            side_effect=["/srv/apps/a", "/srv/apps/b"],
        ):
            with patch("openviper.template.paths.settings") as s:
                s.INSTALLED_APPS = ("a", "b")
                result = list(iter_app_dirs())
        assert len(result) == 2
        assert result[0] == ("a", "/srv/apps/a")
        assert result[1] == ("b", "/srv/apps/b")

    def test_handles_empty_installed_apps(self):
        with patch("openviper.template.paths.settings") as s:
            s.INSTALLED_APPS = ()
            result = list(iter_app_dirs())
        assert result == []

    def test_handles_missing_installed_apps_attribute(self):
        with patch("openviper.template.paths.settings") as s:
            del s.INSTALLED_APPS
            result = list(iter_app_dirs())
        assert result == []


class TestProjectRoot:
    def test_project_root_is_absolute_path(self):
        assert os.path.isabs(paths_mod.PROJECT_ROOT)

    def test_project_root_is_string(self):
        assert isinstance(paths_mod.PROJECT_ROOT, str)
