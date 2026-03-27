"""Smoke tests for initial migration modules.

These modules are simple data declarations, but importing them increases
coverage and ensures they remain importable.
"""

from __future__ import annotations

import importlib


class TestInitialMigrationModules:
    def test_admin_initial_migration_imports(self) -> None:
        mod = importlib.import_module("openviper.admin.migrations.0001_initial")
        assert hasattr(mod, "operations")

    def test_tasks_initial_migration_imports(self) -> None:
        mod = importlib.import_module("openviper.tasks.migrations.0001_initial")
        assert hasattr(mod, "operations")

    def test_auth_initial_migration_imports(self) -> None:
        mod = importlib.import_module("openviper.auth.migrations.0001_initial")
        assert hasattr(mod, "operations")
