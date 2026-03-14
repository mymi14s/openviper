"""Unit tests for openviper/conf/settings.py."""

from __future__ import annotations

import dataclasses
import os
from datetime import timedelta
from unittest.mock import patch

import pytest

from openviper.conf.settings import (
    _SENSITIVE_FIELDS,
    Settings,
    _cast_bool,
    _cast_timedelta,
    _cast_tuple,
    _LazySettings,
    generate_secret_key,
    validate_settings,
)
from openviper.exceptions import SettingsValidationError

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def make_settings(**overrides) -> Settings:
    """Factory for Settings with safe defaults for tests."""
    defaults = {"SECRET_KEY": "test-secret"}
    defaults.update(overrides)
    valid = {f.name for f in dataclasses.fields(Settings)}
    return Settings(**{k: v for k, v in defaults.items() if k in valid})


def make_lazy() -> _LazySettings:
    """Return a fresh unconfigured _LazySettings proxy."""
    return _LazySettings()


# ---------------------------------------------------------------------------
# _cast_* helpers
# ---------------------------------------------------------------------------


class TestCastBool:
    @pytest.mark.parametrize(
        "val,expected",
        [
            ("1", True),
            ("true", True),
            ("yes", True),
            ("on", True),
            ("TRUE", True),
            ("YES", True),
            ("0", False),
            ("false", False),
            ("no", False),
            ("off", False),
            ("", False),
        ],
    )
    def test_cast(self, val, expected):
        assert _cast_bool(val) == expected


class TestCastTuple:
    def test_single_item(self):
        assert _cast_tuple("a") == ("a",)

    def test_multiple_items(self):
        assert _cast_tuple("a,b,c") == ("a", "b", "c")

    def test_strips_whitespace(self):
        assert _cast_tuple(" a , b ") == ("a", "b")

    def test_empty_string_gives_empty(self):
        assert _cast_tuple("") == ()


class TestCastTimedelta:
    def test_seconds(self):
        assert _cast_timedelta("3600") == timedelta(seconds=3600)

    def test_zero(self):
        assert _cast_timedelta("0") == timedelta(seconds=0)


# ---------------------------------------------------------------------------
# Settings defaults
# ---------------------------------------------------------------------------


class TestSettingsDefaults:
    def test_default_project_name(self):
        s = Settings()
        assert s.PROJECT_NAME == "OpenViper Application"

    def test_default_debug_true(self):
        assert Settings().DEBUG is True

    def test_default_secret_key(self):
        # After SECRET_KEY is empty by default, not hardcoded insecure value
        assert Settings().SECRET_KEY == ""

    def test_as_dict_returns_all_fields(self):
        s = Settings()
        d = s.as_dict()
        assert "PROJECT_NAME" in d
        assert "DEBUG" in d
        assert "SECRET_KEY" in d

    def test_as_dict_masks_sensitive_fields_by_default(self):
        s = Settings(SECRET_KEY="super-secret", DATABASE_URL="postgres://user:pass@host/db")
        d = s.as_dict()
        for field_name in _SENSITIVE_FIELDS:
            val = getattr(s, field_name)
            if val:
                assert d[field_name] == "***", f"{field_name} should be masked"

    def test_as_dict_unmasked(self):
        s = Settings(SECRET_KEY="super-secret")
        d = s.as_dict(mask_sensitive=False)
        assert d["SECRET_KEY"] == "super-secret"

    def test_as_dict_empty_sensitive_not_masked(self):
        s = Settings(EMAIL_PASSWORD="")
        d = s.as_dict()
        assert d["EMAIL_PASSWORD"] == ""

    def test_getitem(self):
        s = Settings()
        assert s["PROJECT_NAME"] == "OpenViper Application"

    def test_frozen(self):
        s = Settings()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            s.DEBUG = False  # type: ignore[misc]

    def test_allowed_hosts_tuple(self):
        s = Settings()
        assert isinstance(s.ALLOWED_HOSTS, tuple)

    def test_middleware_tuple(self):
        s = Settings()
        assert isinstance(s.MIDDLEWARE, tuple)

    @pytest.mark.parametrize(
        "field_name,expected_type",
        [
            ("SESSION_TIMEOUT", timedelta),
            ("JWT_ACCESS_TOKEN_EXPIRE", timedelta),
            ("JWT_REFRESH_TOKEN_EXPIRE", timedelta),
        ],
    )
    def test_timedelta_fields(self, field_name, expected_type):
        s = Settings()
        assert isinstance(getattr(s, field_name), expected_type)


# ---------------------------------------------------------------------------
# _LazySettings
# ---------------------------------------------------------------------------


class TestLazySettings:
    def test_configure_programmatic(self):
        lazy = make_lazy()
        s = make_settings()
        lazy.configure(s)
        assert lazy.DEBUG is True

    def test_configure_twice_raises(self):
        lazy = make_lazy()
        lazy.configure(make_settings())
        with pytest.raises(RuntimeError):
            lazy.configure(make_settings())

    def test_attribute_access_before_configure_loads_from_env(self):
        lazy = make_lazy()
        with patch.dict(os.environ, {"OPENVIPER_SETTINGS_MODULE": ""}, clear=False):
            # Should fall back to default Settings when no module set
            val = lazy.DEBUG
            assert isinstance(val, bool)

    def test_configure_then_access(self):
        lazy = make_lazy()
        lazy.configure(Settings(PROJECT_NAME="MyApp"))
        assert lazy.PROJECT_NAME == "MyApp"

    def test_setup_force_reloads(self):
        lazy = make_lazy()
        lazy.configure(make_settings())
        # force=True re-reads env without raising
        with patch.dict(os.environ, {"OPENVIPER_SETTINGS_MODULE": ""}, clear=False):
            lazy._setup(force=True)

    def test_setattr_forbidden_after_configure(self):
        lazy = make_lazy()
        lazy.configure(make_settings())
        with pytest.raises(AttributeError):
            lazy.DEBUG = False


# ---------------------------------------------------------------------------
# generate_secret_key
# ---------------------------------------------------------------------------


class TestGenerateSecretKey:
    def test_returns_string(self):
        assert isinstance(generate_secret_key(), str)

    def test_length_at_least_32(self):
        assert len(generate_secret_key()) >= 32

    def test_unique_each_call(self):
        assert generate_secret_key() != generate_secret_key()


# ---------------------------------------------------------------------------
# validate_settings
# ---------------------------------------------------------------------------


def _prod_settings(**overrides) -> Settings:
    """Settings that pass production validation by default."""
    defaults = {
        "SECRET_KEY": generate_secret_key(64),
        "DATABASE_URL": "postgres://localhost/db",
        "DEBUG": False,
        "SECURE_COOKIES": True,
        "SECURE_SSL_REDIRECT": True,
        "SECURE_HSTS_SECONDS": 31536000,
        "SESSION_COOKIE_SECURE": True,
        "CSRF_COOKIE_SECURE": True,
        "OPENAPI_ENABLED": False,
        "ALLOWED_HOSTS": ("example.com",),
        "CORS_ALLOWED_HEADERS": ("Authorization", "Content-Type"),
    }
    defaults.update(overrides)
    return Settings(**defaults)


class TestValidateSettings:
    def test_valid_production_settings(self):
        validate_settings(_prod_settings(), "production")

    def test_valid_development_settings(self):
        s = Settings(DATABASE_URL="sqlite:///db.sqlite3")
        validate_settings(s, "development")

    def test_production_rejects_debug(self):
        with pytest.raises(SettingsValidationError, match="DEBUG"):
            validate_settings(_prod_settings(DEBUG=True), "production")

    def test_production_rejects_insecure_secret_key(self):
        with pytest.raises(SettingsValidationError, match="SECRET_KEY"):
            validate_settings(_prod_settings(SECRET_KEY="INSECURE-CHANGE-ME"), "production")

    def test_production_rejects_short_secret_key(self):
        with pytest.raises(SettingsValidationError, match="SECRET_KEY.*50"):
            validate_settings(_prod_settings(SECRET_KEY="short"), "production")

    def test_production_rejects_no_ssl_redirect(self):
        with pytest.raises(SettingsValidationError, match="SECURE_SSL_REDIRECT"):
            validate_settings(_prod_settings(SECURE_SSL_REDIRECT=False), "production")

    def test_production_rejects_low_hsts(self):
        with pytest.raises(SettingsValidationError, match="SECURE_HSTS_SECONDS"):
            validate_settings(_prod_settings(SECURE_HSTS_SECONDS=0), "production")

    def test_production_rejects_insecure_session_cookie(self):
        with pytest.raises(SettingsValidationError, match="SESSION_COOKIE_SECURE"):
            validate_settings(_prod_settings(SESSION_COOKIE_SECURE=False), "production")

    def test_production_rejects_insecure_csrf_cookie(self):
        with pytest.raises(SettingsValidationError, match="CSRF_COOKIE_SECURE"):
            validate_settings(_prod_settings(CSRF_COOKIE_SECURE=False), "production")

    def test_production_rejects_openapi_enabled(self):
        with pytest.raises(SettingsValidationError, match="OPENAPI_ENABLED"):
            validate_settings(_prod_settings(OPENAPI_ENABLED=True), "production")

    def test_production_rejects_wildcard_cors_headers(self):
        with pytest.raises(SettingsValidationError, match="CORS_ALLOWED_HEADERS"):
            validate_settings(_prod_settings(CORS_ALLOWED_HEADERS=("*",)), "production")

    def test_rejects_none_jwt_algorithm(self):
        with pytest.raises(SettingsValidationError, match="JWT_ALGORITHM"):
            validate_settings(
                Settings(DATABASE_URL="sqlite:///db.sqlite3", JWT_ALGORITHM="none"),
                "development",
            )

    def test_missing_database_url(self):
        with pytest.raises(SettingsValidationError, match="DATABASE_URL"):
            validate_settings(Settings(), "development")

    def test_production_rejects_empty_allowed_hosts(self):
        with pytest.raises(SettingsValidationError, match="ALLOWED_HOSTS"):
            validate_settings(_prod_settings(ALLOWED_HOSTS=()), "production")
