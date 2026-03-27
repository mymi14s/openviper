"""Unit tests for branching logic in the auth initial migration module."""

from __future__ import annotations

import importlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import patch


def _migration_module():
    return importlib.import_module("openviper.auth.migrations.0001_initial")


def test_resolve_user_dependency_empty_for_default() -> None:
    mod = _migration_module()
    with patch.object(
        mod,
        "_openviper_settings",
        SimpleNamespace(USER_MODEL=None, AUTH_USER_MODEL=mod._AUTH_USER),
    ):
        assert mod._resolve_user_dependency() == []


def test_resolve_user_dependency_for_custom_user() -> None:
    mod = _migration_module()
    with patch.object(
        mod,
        "_openviper_settings",
        SimpleNamespace(USER_MODEL="accounts.models.User", AUTH_USER_MODEL=None),
    ):
        assert mod._resolve_user_dependency() == [("accounts", "0001_initial")]


def test_resolve_user_table_reads_table_name() -> None:
    mod = _migration_module()

    accounts_mod = types.ModuleType("accounts.models")

    class User:
        class Meta:
            table_name = "accounts_users"

    accounts_mod.User = User

    with (
        patch.object(
            mod,
            "_openviper_settings",
            SimpleNamespace(USER_MODEL="accounts.models.User", AUTH_USER_MODEL=None),
        ),
        patch_modules({"accounts.models": accounts_mod}),
    ):
        assert mod._resolve_user_table() == "accounts_users"


def test_resolve_user_table_falls_back_on_import_error() -> None:
    mod = _migration_module()
    with patch.object(
        mod,
        "_openviper_settings",
        SimpleNamespace(USER_MODEL="missing.models.User", AUTH_USER_MODEL=None),
    ):
        assert mod._resolve_user_table() == "auth_users"


class patch_modules:
    """Context manager for temporary sys.modules additions."""

    def __init__(self, mapping: dict[str, types.ModuleType]) -> None:
        self.mapping = mapping
        self.original: dict[str, object] = {}

    def __enter__(self):
        for name, module in self.mapping.items():
            if name in sys.modules:
                self.original[name] = sys.modules[name]
            sys.modules[name] = module
        return self

    def __exit__(self, exc_type, exc, tb):
        for name in self.mapping:
            if name in self.original:
                sys.modules[name] = self.original[name]
            else:
                sys.modules.pop(name, None)
        return False
