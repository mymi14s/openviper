"""Tests for import_models_module and NoModelsModule.

Regression tests: broken imports inside a models module must raise
CommandError, not be silently swallowed (which caused schemas to be
deleted because models failed to register).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from openviper.core.management.base import CommandError, NoModelsModule
from openviper.core.management.utils import import_models_module


class TestImportModelsModule:
    """Test that import_models_module surfaces real import errors."""

    def test_no_models_module_raises_no_models(self, tmp_path: Path) -> None:
        """An app without a models.py raises NoModelsModule, not CommandError."""
        app = tmp_path / "no_models_app"
        app.mkdir()
        (app / "__init__.py").write_text("")

        sys.path.insert(0, str(tmp_path))
        try:
            with pytest.raises(NoModelsModule):
                import_models_module("no_models_app", str(app))
        finally:
            sys.path.remove(str(tmp_path))
            sys.modules.pop("no_models_app", None)

    def test_broken_import_raises_command_error(self, tmp_path: Path) -> None:
        """A models.py with a broken import raises CommandError, not NoModelsModule."""
        app = tmp_path / "broken_app"
        app.mkdir()
        (app / "__init__.py").write_text("")
        (app / "models.py").write_text(
            "from openviper.contrib.fields.countryfields import CurrencyField\n"
            "class Foo:\n"
            "    pass\n"
        )

        sys.path.insert(0, str(tmp_path))
        try:
            with pytest.raises(CommandError) as exc_info:
                import_models_module("broken_app", str(app))
            assert "countryfields" in str(exc_info.value).lower() or \
                "failed to import" in str(exc_info.value).lower()
        finally:
            sys.path.remove(str(tmp_path))
            for mod in list(sys.modules):
                if mod.startswith("broken_app"):
                    del sys.modules[mod]

    def test_valid_models_module_imports(self, tmp_path: Path) -> None:
        """A valid models.py imports successfully."""
        app = tmp_path / "good_app"
        app.mkdir()
        (app / "__init__.py").write_text("")
        (app / "models.py").write_text("VALUE = 42\n")

        sys.path.insert(0, str(tmp_path))
        try:
            mod = import_models_module("good_app", str(app))
            assert mod.VALUE == 42
        finally:
            sys.path.remove(str(tmp_path))
            for mod_name in list(sys.modules):
                if mod_name.startswith("good_app"):
                    del sys.modules[mod_name]
