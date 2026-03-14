"""Unit tests for openviper.utils.timezone, importlib, and module_resolver."""

from __future__ import annotations

import datetime
import zoneinfo
from unittest.mock import patch

import click
import pytest

from openviper.conf import settings
from openviper.exceptions import NotFound
from openviper.utils.importlib import import_string, reset_import_cache
from openviper.utils.module_resolver import ResolvedModule, resolve_target
from openviper.utils.timezone import (
    get_current_timezone,
    is_aware,
    is_naive,
    make_aware,
    make_naive,
    now,
)

# ---------------------------------------------------------------------------
# timezone
# ---------------------------------------------------------------------------


class TestTimezone:
    """Tests for openviper.utils.timezone helpers."""

    def test_now_returns_datetime(self):

        result = now()
        assert isinstance(result, datetime.datetime)

    def test_now_aware_when_use_tz_true(self):

        with patch.object(type(settings), "USE_TZ", new=True, create=True):
            result = now()
        # When USE_TZ=True, now() returns an aware UTC datetime
        assert result.tzinfo is not None

    def test_now_naive_when_use_tz_false(self):

        with patch.object(type(settings), "USE_TZ", new=False, create=True):
            result = now()
        assert result.tzinfo is None

    def test_is_aware_with_aware_datetime(self):

        dt = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
        assert is_aware(dt) is True

    def test_is_aware_with_naive_datetime(self):

        dt = datetime.datetime(2024, 1, 1)
        assert is_aware(dt) is False

    def test_is_naive_with_naive_datetime(self):

        dt = datetime.datetime(2024, 1, 1)
        assert is_naive(dt) is True

    def test_is_naive_with_aware_datetime(self):

        dt = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
        assert is_naive(dt) is False

    def test_make_aware(self):

        naive = datetime.datetime(2024, 6, 15, 12, 0, 0)
        tz = zoneinfo.ZoneInfo("UTC")
        aware = make_aware(naive, tz)
        assert aware.tzinfo is not None

    def test_make_aware_raises_on_already_aware(self):

        aware = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
        with pytest.raises(ValueError, match="naive"):
            make_aware(aware, zoneinfo.ZoneInfo("UTC"))

    def test_make_naive(self):

        aware = datetime.datetime(2024, 6, 15, 12, 0, tzinfo=datetime.UTC)
        tz = zoneinfo.ZoneInfo("UTC")
        naive = make_naive(aware, tz)
        assert naive.tzinfo is None

    def test_make_naive_raises_on_naive(self):

        naive = datetime.datetime(2024, 1, 1)
        with pytest.raises(ValueError, match="aware"):
            make_naive(naive, zoneinfo.ZoneInfo("UTC"))

    def test_get_current_timezone_returns_zone_info(self):

        with patch.object(type(settings), "TIME_ZONE", new="UTC", create=True):
            tz = get_current_timezone()
        assert isinstance(tz, zoneinfo.ZoneInfo)


# ---------------------------------------------------------------------------
# importlib
# ---------------------------------------------------------------------------


class TestImportString:
    def setup_method(self):
        reset_import_cache()

    def test_imports_class(self):
        cls = import_string("openviper.exceptions.NotFound")

        assert cls is NotFound

    def test_imports_function(self):
        fn = import_string("openviper.utils.importlib.reset_import_cache")
        assert fn is reset_import_cache

    def test_import_error_on_bad_module(self):
        with pytest.raises((ImportError, ModuleNotFoundError)):
            import_string("nonexistent.module.Class")

    def test_attribute_error_on_bad_attribute(self):
        with pytest.raises(AttributeError):
            import_string("openviper.exceptions.NonExistentClass")

    def test_reset_clears_cache(self):
        import_string("openviper.exceptions.NotFound")
        reset_import_cache()
        # After reset, it should still work (reimport)
        cls = import_string("openviper.exceptions.NotFound")

        assert cls is NotFound


# ---------------------------------------------------------------------------
# module_resolver
# ---------------------------------------------------------------------------


class TestResolveTarget:
    def test_dot_target_with_models_py(self, tmp_path):
        (tmp_path / "models.py").touch()
        result = resolve_target(".", cwd=tmp_path)
        assert isinstance(result, ResolvedModule)
        assert result.is_root is True
        assert result.app_label == tmp_path.name

    def test_dot_target_with_routes_py(self, tmp_path):
        (tmp_path / "routes.py").touch()
        result = resolve_target(".", cwd=tmp_path)
        assert result.is_root is True

    def test_dot_target_no_files_raises(self, tmp_path):

        with pytest.raises(click.ClickException):
            resolve_target(".", cwd=tmp_path)

    def test_dot_target_invalid_dir_name_raises(self, tmp_path):

        bad_dir = tmp_path / "123-invalid"
        bad_dir.mkdir()
        (bad_dir / "models.py").touch()
        with pytest.raises(click.ClickException):
            resolve_target(".", cwd=bad_dir)

    def test_named_module_target(self, tmp_path):
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        (app_dir / "models.py").touch()
        result = resolve_target("myapp", cwd=tmp_path)
        assert result.app_label == "myapp"
        assert result.is_root is False
        assert result.models_module == "myapp.models"

    def test_named_module_not_found_raises(self, tmp_path):

        with pytest.raises(click.ClickException, match="not found"):
            resolve_target("missing_module", cwd=tmp_path)

    def test_named_module_no_models_or_routes_raises(self, tmp_path):

        empty_dir = tmp_path / "emptyapp"
        empty_dir.mkdir()
        with pytest.raises(click.ClickException):
            resolve_target("emptyapp", cwd=tmp_path)

    def test_resolved_module_fields(self, tmp_path):
        (tmp_path / "models.py").touch()
        result = resolve_target(".", cwd=tmp_path)
        assert result.app_path == tmp_path
        assert result.models_module.endswith(".models")

    def test_named_module_app_path(self, tmp_path):
        app_dir = tmp_path / "shop"
        app_dir.mkdir()
        (app_dir / "routes.py").touch()
        result = resolve_target("shop", cwd=tmp_path)
        assert result.app_path == app_dir
