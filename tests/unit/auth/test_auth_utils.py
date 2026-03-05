import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.utils import discover_models, get_user_model, sync_content_types

# ── get_user_model ────────────────────────────────────────────────────────────


def test_get_user_model_default():
    # Should return openviper.auth.models.User by default
    model = get_user_model()
    assert model.__name__ == "User"
    assert model.__module__ == "openviper.auth.models"


def test_get_user_model_custom_success():
    """When USER_MODEL points to a valid import path, that class is returned."""
    fake_class = MagicMock()
    fake_class.__name__ = "CustomUser"

    # settings is imported inside get_user_model via `from openviper.conf import settings`
    # so we patch openviper.conf.settings (the attribute on the conf module).
    with patch("openviper.conf.settings") as mock_settings:
        mock_settings.USER_MODEL = "myapp.models.CustomUser"
        mock_settings.AUTH_USER_MODEL = None

        with patch("openviper.utils.import_string", return_value=fake_class) as mock_import:
            result = get_user_model()

    mock_import.assert_called_once_with("myapp.models.CustomUser")
    assert result is fake_class


def test_get_user_model_custom_import_fails_falls_back_to_default():
    """When import_string raises ImportError, fall back to the built-in User model."""
    with patch("openviper.conf.settings") as mock_settings:
        mock_settings.USER_MODEL = "nonexistent.module.User"
        mock_settings.AUTH_USER_MODEL = None

        with patch("openviper.utils.import_string", side_effect=ImportError("no module")):
            result = get_user_model()

    from openviper.auth.models import User

    assert result is User


def test_get_user_model_custom_attribute_error_falls_back_to_default():
    """When import_string raises AttributeError, fall back to the built-in User model."""
    with patch("openviper.conf.settings") as mock_settings:
        mock_settings.USER_MODEL = "myapp.models.MissingUser"
        mock_settings.AUTH_USER_MODEL = None

        with patch("openviper.utils.import_string", side_effect=AttributeError("no attr")):
            result = get_user_model()

    from openviper.auth.models import User

    assert result is User


def test_get_user_model_no_custom_setting_returns_default():
    """With no USER_MODEL or AUTH_USER_MODEL in settings, the built-in User is returned."""
    with patch("openviper.conf.settings") as mock_settings:
        mock_settings.USER_MODEL = None
        mock_settings.AUTH_USER_MODEL = None

        result = get_user_model()

    from openviper.auth.models import User

    assert result is User


def test_get_user_model_uses_auth_user_model_fallback():
    """AUTH_USER_MODEL is used when USER_MODEL is absent from settings."""
    fake_class = MagicMock()
    fake_class.__name__ = "LegacyUser"

    # Use a plain class so that .USER_MODEL raises AttributeError and
    # getattr falls through to AUTH_USER_MODEL as the default value.
    class _FakeSettings:
        AUTH_USER_MODEL = "legacy.models.LegacyUser"

    with (
        patch("openviper.conf.settings", new=_FakeSettings()),
        patch("openviper.utils.import_string", return_value=fake_class),
    ):
        result = get_user_model()

    assert result is fake_class


# ── discover_models ───────────────────────────────────────────────────────────


def test_discover_models_direct_import_success(caplog):
    """When importlib.import_module succeeds, AppResolver is not consulted."""
    # settings and AppResolver are imported inside discover_models(), so we patch
    # them at their source module locations.
    with patch("openviper.conf.settings") as mock_settings:
        mock_settings.INSTALLED_APPS = ["myapp", "otherapp"]

        # AppResolver is imported inside discover_models as:
        #   from openviper.core.app_resolver import AppResolver
        with patch("openviper.core.app_resolver.AppResolver") as mock_resolver_cls:
            # importlib is imported at module level in openviper.auth.utils,
            # so patch via the module reference.
            with (
                patch("openviper.auth.utils.importlib.import_module") as mock_import,
                caplog.at_level(logging.DEBUG, logger="openviper.auth"),
            ):
                discover_models()

    assert mock_import.call_count == 2
    mock_import.assert_any_call("myapp.models")
    mock_import.assert_any_call("otherapp.models")
    mock_resolver_cls.return_value.resolve_app.assert_not_called()


def test_discover_models_falls_back_to_app_resolver_on_import_error(tmp_path):
    """When importlib.import_module raises ImportError, AppResolver path is tried."""
    models_file = tmp_path / "models.py"
    models_file.write_text("# models")

    mock_resolver = MagicMock()
    mock_resolver.resolve_app.return_value = (str(tmp_path), True)

    fake_spec = MagicMock()
    fake_spec.loader = MagicMock()
    fake_module = MagicMock()

    with patch("openviper.conf.settings") as mock_settings:
        mock_settings.INSTALLED_APPS = ["localapp"]

        with patch("openviper.core.app_resolver.AppResolver", return_value=mock_resolver):
            with patch(
                "openviper.auth.utils.importlib.util.spec_from_file_location",
                return_value=fake_spec,
            ):
                with patch(
                    "openviper.auth.utils.importlib.util.module_from_spec", return_value=fake_module
                ):
                    with patch(
                        "openviper.auth.utils.importlib.import_module", side_effect=ImportError
                    ):
                        discover_models()

    mock_resolver.resolve_app.assert_called_once_with("localapp")
    fake_spec.loader.exec_module.assert_called_once_with(fake_module)


def test_discover_models_resolver_not_found_skips():
    """When the resolver cannot find the app, nothing is loaded."""
    mock_resolver = MagicMock()
    mock_resolver.resolve_app.return_value = (None, False)

    with patch("openviper.conf.settings") as mock_settings:
        mock_settings.INSTALLED_APPS = ["missingapp"]

        with (
            patch("openviper.core.app_resolver.AppResolver", return_value=mock_resolver),
            patch("openviper.auth.utils.importlib.import_module", side_effect=ImportError),
        ):
            discover_models()

    mock_resolver.resolve_app.assert_called_once_with("missingapp")


def test_discover_models_resolver_found_but_no_models_file(tmp_path):
    """When app path is found but models.py doesn't exist, loader is not called."""
    # tmp_path has no models.py
    mock_resolver = MagicMock()
    mock_resolver.resolve_app.return_value = (str(tmp_path), True)

    with patch("openviper.conf.settings") as mock_settings:
        mock_settings.INSTALLED_APPS = ["nomodels"]

        with patch("openviper.core.app_resolver.AppResolver", return_value=mock_resolver):
            with patch(
                "openviper.auth.utils.importlib.util.spec_from_file_location"
            ) as mock_spec_fn:
                with patch("openviper.auth.utils.importlib.import_module", side_effect=ImportError):
                    discover_models()

    mock_spec_fn.assert_not_called()


def test_discover_models_loader_exec_exception_is_warned(tmp_path, caplog):
    """When spec.loader.exec_module raises, a warning is logged and execution continues."""
    models_file = tmp_path / "models.py"
    models_file.write_text("# models")

    mock_resolver = MagicMock()
    mock_resolver.resolve_app.return_value = (str(tmp_path), True)

    fake_spec = MagicMock()
    fake_spec.loader = MagicMock()
    fake_spec.loader.exec_module.side_effect = RuntimeError("bad module")
    fake_module = MagicMock()

    with patch("openviper.conf.settings") as mock_settings:
        mock_settings.INSTALLED_APPS = ["badapp"]

        with patch("openviper.core.app_resolver.AppResolver", return_value=mock_resolver):
            with patch(
                "openviper.auth.utils.importlib.util.spec_from_file_location",
                return_value=fake_spec,
            ):
                with patch(
                    "openviper.auth.utils.importlib.util.module_from_spec", return_value=fake_module
                ):
                    with patch(
                        "openviper.auth.utils.importlib.import_module", side_effect=ImportError
                    ):
                        with caplog.at_level(logging.WARNING, logger="openviper.auth"):
                            discover_models()  # must not raise

    assert any("Failed to import models" in r.message for r in caplog.records)


def test_discover_models_empty_installed_apps():
    """Empty INSTALLED_APPS list means nothing is imported."""
    with patch("openviper.conf.settings") as mock_settings:
        mock_settings.INSTALLED_APPS = []

        with patch("openviper.auth.utils.importlib.import_module") as mock_import:
            discover_models()

    mock_import.assert_not_called()


def test_discover_models_no_installed_apps_attribute():
    """If INSTALLED_APPS is absent from settings, an empty list is used."""

    class _FakeSettings:
        pass  # no INSTALLED_APPS attribute

    with (
        patch("openviper.conf.settings", new=_FakeSettings()),
        patch("openviper.auth.utils.importlib.import_module") as mock_import,
    ):
        discover_models()

    mock_import.assert_not_called()


# ── sync_content_types ────────────────────────────────────────────────────────
# ContentType is imported inside sync_content_types as:
#     from openviper.auth.models import ContentType
# ModelMeta is imported as:
#     from openviper.db.models import ModelMeta
# So we patch them at their source locations.


@pytest.mark.asyncio
async def test_sync_content_types_creates_new_entries(caplog):
    """New models not yet in the DB get a ContentType created."""

    mock_model_a = MagicMock()
    mock_model_a._app_name = "blog"
    mock_model_a._model_name = "Post"

    mock_ct_objects = MagicMock()
    mock_ct_objects.all = AsyncMock(return_value=[])
    mock_ct_objects.create = AsyncMock()

    with (
        patch("openviper.auth.utils.discover_models"),
        patch("openviper.auth.models.ContentType") as mock_ct_cls,
    ):
        mock_ct_cls.objects = mock_ct_objects

        with patch("openviper.db.models.ModelMeta") as mock_model_meta:
            mock_model_meta.registry = {"blog.Post": mock_model_a}

            with caplog.at_level(logging.INFO, logger="openviper.auth"):
                await sync_content_types()

    mock_ct_objects.create.assert_called_once_with(app_label="blog", model="Post")


@pytest.mark.asyncio
async def test_sync_content_types_skips_existing_entries():
    """Models already in the DB do not trigger a create call."""

    mock_model_a = MagicMock()
    mock_model_a._app_name = "blog"
    mock_model_a._model_name = "Post"

    existing_ct = MagicMock()
    existing_ct.app_label = "blog"
    existing_ct.model = "Post"

    mock_ct_objects = MagicMock()
    mock_ct_objects.all = AsyncMock(return_value=[existing_ct])
    mock_ct_objects.create = AsyncMock()

    with (
        patch("openviper.auth.utils.discover_models"),
        patch("openviper.auth.models.ContentType") as mock_ct_cls,
    ):
        mock_ct_cls.objects = mock_ct_objects

        with patch("openviper.db.models.ModelMeta") as mock_model_meta:
            mock_model_meta.registry = {"blog.Post": mock_model_a}
            await sync_content_types()

    mock_ct_objects.create.assert_not_called()


@pytest.mark.asyncio
async def test_sync_content_types_deletes_stale_entries(caplog):
    """Content types whose models have been removed are deleted."""

    stale_ct = MagicMock()
    stale_ct.app_label = "oldapp"
    stale_ct.model = "Ghost"
    stale_ct.delete = AsyncMock()

    mock_ct_objects = MagicMock()
    mock_ct_objects.all = AsyncMock(return_value=[stale_ct])
    mock_ct_objects.create = AsyncMock()

    with (
        patch("openviper.auth.utils.discover_models"),
        patch("openviper.auth.models.ContentType") as mock_ct_cls,
    ):
        mock_ct_cls.objects = mock_ct_objects

        with patch("openviper.db.models.ModelMeta") as mock_model_meta:
            mock_model_meta.registry = {}

            with caplog.at_level(logging.INFO, logger="openviper.auth"):
                await sync_content_types()

    stale_ct.delete.assert_called_once()


@pytest.mark.asyncio
async def test_sync_content_types_skips_base_model_placeholder():
    """The default/Model placeholder inserted by ModelMeta is skipped."""

    base_model = MagicMock()
    base_model._app_name = "default"
    base_model._model_name = "Model"

    real_model = MagicMock()
    real_model._app_name = "myapp"
    real_model._model_name = "Article"

    mock_ct_objects = MagicMock()
    mock_ct_objects.all = AsyncMock(return_value=[])
    mock_ct_objects.create = AsyncMock()

    with (
        patch("openviper.auth.utils.discover_models"),
        patch("openviper.auth.models.ContentType") as mock_ct_cls,
    ):
        mock_ct_cls.objects = mock_ct_objects

        with patch("openviper.db.models.ModelMeta") as mock_model_meta:
            mock_model_meta.registry = {
                "default.Model": base_model,
                "myapp.Article": real_model,
            }
            await sync_content_types()

    # Only Article should be created, not the base placeholder
    mock_ct_objects.create.assert_called_once_with(app_label="myapp", model="Article")


@pytest.mark.asyncio
async def test_sync_content_types_db_unavailable_returns_early(caplog):
    """If ContentType.objects.all() raises (table doesn't exist yet), returns early."""

    mock_ct_objects = MagicMock()
    mock_ct_objects.all = AsyncMock(side_effect=Exception("no such table"))
    mock_ct_objects.create = AsyncMock()

    with (
        patch("openviper.auth.utils.discover_models"),
        patch("openviper.auth.models.ContentType") as mock_ct_cls,
    ):
        mock_ct_cls.objects = mock_ct_objects

        with patch("openviper.db.models.ModelMeta") as mock_model_meta:
            mock_model_meta.registry = {}

            with caplog.at_level(logging.DEBUG, logger="openviper.auth"):
                await sync_content_types()

    mock_ct_objects.create.assert_not_called()
    assert any("Could not fetch" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_sync_content_types_no_changes_does_not_log_info(caplog):
    """When nothing changes (no creates, no deletes), no INFO is logged."""

    model_a = MagicMock()
    model_a._app_name = "myapp"
    model_a._model_name = "Thing"

    existing_ct = MagicMock()
    existing_ct.app_label = "myapp"
    existing_ct.model = "Thing"

    mock_ct_objects = MagicMock()
    mock_ct_objects.all = AsyncMock(return_value=[existing_ct])
    mock_ct_objects.create = AsyncMock()

    with (
        patch("openviper.auth.utils.discover_models"),
        patch("openviper.auth.models.ContentType") as mock_ct_cls,
    ):
        mock_ct_cls.objects = mock_ct_objects

        with patch("openviper.db.models.ModelMeta") as mock_model_meta:
            mock_model_meta.registry = {"myapp.Thing": model_a}

            with caplog.at_level(logging.INFO, logger="openviper.auth"):
                await sync_content_types()

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) == 0


@pytest.mark.asyncio
async def test_sync_content_types_calls_discover_models():
    """discover_models() is always called at the start of sync_content_types."""

    mock_ct_objects = MagicMock()
    mock_ct_objects.all = AsyncMock(return_value=[])
    mock_ct_objects.create = AsyncMock()

    with (
        patch("openviper.auth.utils.discover_models") as mock_discover,
        patch("openviper.auth.models.ContentType") as mock_ct_cls,
    ):
        mock_ct_cls.objects = mock_ct_objects

        with patch("openviper.db.models.ModelMeta") as mock_model_meta:
            mock_model_meta.registry = {}
            await sync_content_types()

    mock_discover.assert_called_once()
