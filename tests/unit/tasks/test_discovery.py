"""Tests for openviper.tasks.discovery - app task discovery."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openviper.tasks.discovery import discover_tasks
from openviper.tasks.registry import Registry


class TestDiscoverTasks:
    """Test application task discovery."""

    def setup_method(self) -> None:
        Registry().clear()

    def test_discover_imports_tasks_module(self) -> None:
        with patch("importlib.import_module") as mock_import:
            discover_tasks(["myapp"])
            mock_import.assert_called_with("myapp.tasks")

    def test_discover_skips_missing_tasks_module(self) -> None:
        with patch("importlib.import_module", side_effect=ModuleNotFoundError):
            discover_tasks(["missing_app"])

    def test_discover_marks_app_as_discovered(self) -> None:
        registry = Registry()
        with patch("importlib.import_module", side_effect=ModuleNotFoundError):
            discover_tasks(["test_app"])
        assert registry.is_discovered("test_app")

    def test_discover_does_not_re_scan(self) -> None:
        registry = Registry()
        registry.mark_discovered("already_scanned")
        with patch("importlib.import_module") as mock_import:
            discover_tasks(["already_scanned"])
            mock_import.assert_not_called()
