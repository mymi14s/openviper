"""Additional branch tests for openviper.auth.utils.

These tests focus on coverage gaps around lazy model discovery and
ContentType synchronization logic.
"""

from __future__ import annotations

import importlib
import logging
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.models import User as DefaultUser
from openviper.auth.utils import discover_models, get_user_model, sync_content_types

_REAL_IMPORT_MODULE = importlib.import_module


class TestGetUserModelBranches:
    def test_uses_legacy_auth_user_model_setting(self) -> None:
        custom_model = object()
        with patch("openviper.auth.utils.settings") as mock_settings:
            del mock_settings.USER_MODEL
            mock_settings.AUTH_USER_MODEL = "legacy.CustomUser"
            with patch("openviper.auth.utils.import_string", return_value=custom_model):
                assert get_user_model() is custom_model

    def test_falls_back_on_attribute_error(self) -> None:
        with patch("openviper.auth.utils.settings") as mock_settings:
            mock_settings.USER_MODEL = "bad.CustomUser"
            with patch("openviper.auth.utils.import_string", side_effect=AttributeError):
                assert get_user_model() is DefaultUser


class TestDiscoverModelsBranches:
    def test_imports_models_via_resolved_path(self, tmp_path: Path) -> None:
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        (app_dir / "models.py").write_text("x = 1\n")

        loader = MagicMock()
        spec = types.SimpleNamespace(loader=loader)

        def import_side_effect(name: str):
            if name == "myapp.models":
                raise ImportError
            return _REAL_IMPORT_MODULE(name)

        with (
            patch("openviper.auth.utils.settings") as mock_settings,
            patch("openviper.auth.utils.AppResolver") as mock_resolver_cls,
            patch("openviper.auth.utils.importlib.import_module", side_effect=import_side_effect),
            patch(
                "openviper.auth.utils.importlib.util.spec_from_file_location",
                return_value=spec,
            ) as mock_spec,
            patch("openviper.auth.utils.importlib.util.module_from_spec") as mock_mod_from_spec,
        ):
            mock_settings.INSTALLED_APPS = ["myapp"]
            resolver = MagicMock()
            resolver.resolve_app.return_value = (str(app_dir), True)
            mock_resolver_cls.return_value = resolver

            module = types.ModuleType("myapp.models")
            mock_mod_from_spec.return_value = module

            discover_models()

        mock_spec.assert_called_once()
        loader.exec_module.assert_called_once_with(module)

    def test_ignores_missing_models_file_when_resolver_fails(self) -> None:
        def import_side_effect(name: str):
            if name == "notfound.models":
                raise ImportError
            return _REAL_IMPORT_MODULE(name)

        with (
            patch("openviper.auth.utils.settings") as mock_settings,
            patch("openviper.auth.utils.AppResolver") as mock_resolver_cls,
            patch("openviper.auth.utils.importlib.import_module", side_effect=import_side_effect),
        ):
            mock_settings.INSTALLED_APPS = ["notfound"]
            resolver = MagicMock()
            resolver.resolve_app.return_value = (None, False)
            mock_resolver_cls.return_value = resolver

            discover_models()

    def test_logs_warning_when_models_exec_fails(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING, logger="openviper.auth")

        app_dir = tmp_path / "warnapp"
        app_dir.mkdir()
        (app_dir / "models.py").write_text("x = 1\n")

        loader = MagicMock()
        loader.exec_module.side_effect = RuntimeError("boom")
        spec = types.SimpleNamespace(loader=loader)

        def import_side_effect(name: str):
            if name == "warnapp.models":
                raise ImportError
            return _REAL_IMPORT_MODULE(name)

        with (
            patch("openviper.auth.utils.settings") as mock_settings,
            patch("openviper.auth.utils.AppResolver") as mock_resolver_cls,
            patch("openviper.auth.utils.importlib.import_module", side_effect=import_side_effect),
            patch(
                "openviper.auth.utils.importlib.util.spec_from_file_location",
                return_value=spec,
            ),
            patch(
                "openviper.auth.utils.importlib.util.module_from_spec",
                return_value=types.ModuleType("warnapp.models"),
            ),
        ):
            mock_settings.INSTALLED_APPS = ["warnapp"]
            resolver = MagicMock()
            resolver.resolve_app.return_value = (str(app_dir), True)
            mock_resolver_cls.return_value = resolver

            discover_models()

        assert any("Failed to import models" in rec.message for rec in caplog.records)


class TestSyncContentTypesBranches:
    @pytest.mark.asyncio
    async def test_creates_and_deletes_and_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.INFO, logger="openviper.auth")

        base_model = type("BaseModel", (), {"_app_name": "default", "_model_name": "Model"})
        existing_model = type("ExistingModel", (), {"_app_name": "app", "_model_name": "Existing"})
        new_model = type("NewModel", (), {"_app_name": "app", "_model_name": "New"})

        stale_ct = MagicMock(app_label="old", model="Stale")
        stale_ct.delete = AsyncMock()
        keep_ct = MagicMock(app_label="app", model="Existing")
        keep_ct.delete = AsyncMock()

        content_type_objects = MagicMock()
        content_type_objects.all = AsyncMock(return_value=[keep_ct, stale_ct])
        content_type_objects.create = AsyncMock()

        with (
            patch("openviper.auth.utils.discover_models"),
            patch("openviper.auth.utils.ModelMeta") as mock_meta,
            patch("openviper.auth.utils.ContentType") as mock_content_type,
        ):
            mock_meta.registry = {"base": base_model, "e": existing_model, "n": new_model}
            mock_content_type.objects = content_type_objects

            await sync_content_types()

        content_type_objects.create.assert_awaited_once_with(app_label="app", model="New")
        stale_ct.delete.assert_awaited_once()
        assert any("ContentType synchronization" in rec.message for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_no_changes_does_not_log_info(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.INFO, logger="openviper.auth")

        model = type("Only", (), {"_app_name": "app", "_model_name": "Only"})
        ct = MagicMock(app_label="app", model="Only")
        ct.delete = AsyncMock()

        objects = MagicMock()
        objects.all = AsyncMock(return_value=[ct])
        objects.create = AsyncMock()

        with (
            patch("openviper.auth.utils.discover_models"),
            patch("openviper.auth.utils.ModelMeta") as mock_meta,
            patch("openviper.auth.utils.ContentType") as mock_content_type,
        ):
            mock_meta.registry = {"only": model}
            mock_content_type.objects = objects

            await sync_content_types()

        objects.create.assert_not_awaited()
        ct.delete.assert_not_awaited()
        assert not any("ContentType synchronization" in rec.message for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_returns_early_when_content_type_query_fails(self) -> None:
        objects = MagicMock()
        objects.all = AsyncMock(side_effect=Exception("no table"))
        objects.create = AsyncMock()

        with (
            patch("openviper.auth.utils.discover_models"),
            patch("openviper.auth.utils.ModelMeta") as mock_meta,
            patch("openviper.auth.utils.ContentType") as mock_content_type,
        ):
            mock_meta.registry = {
                "only": type("Only", (), {"_app_name": "app", "_model_name": "Only"})
            }
            mock_content_type.objects = objects

            await sync_content_types()

        objects.create.assert_not_awaited()
