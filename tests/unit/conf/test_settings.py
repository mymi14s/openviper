"""Unit tests for openviper.conf.settings."""

from __future__ import annotations

import dataclasses
import json
import logging
import sys
from datetime import timedelta

import pytest

from openviper.conf.settings import (
    Settings,
    _apply_env_overrides,
    _auto_include_project_app,
    _cast_bool,
    _cast_env_value,
    _cast_timedelta,
    _cast_tuple,
    _JsonFormatter,
    _LazySettings,
    _OVDefaultHandler,
    configure_logging,
    generate_secret_key,
    validate_settings,
)
from openviper.exceptions import SettingsValidationError

# ---------------------------------------------------------------------------
# Settings dataclass
# ---------------------------------------------------------------------------


class TestSettingsDefaults:
    def test_is_frozen_dataclass(self):
        s = Settings()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            s.DEBUG = False

    def test_default_debug_true(self):
        assert Settings().DEBUG is True

    def test_default_use_tz_true(self):
        assert Settings().USE_TZ is True

    def test_default_time_zone_utc(self):
        assert Settings().TIME_ZONE == "UTC"

    def test_default_allowed_hosts(self):
        hosts = Settings().ALLOWED_HOSTS
        assert "localhost" in hosts

    def test_getitem_access(self):
        s = Settings()
        assert s["DEBUG"] == s.DEBUG


class TestSettingsAsDict:
    def test_returns_dict(self):
        s = Settings()
        d = s.as_dict()
        assert isinstance(d, dict)

    def test_sensitive_fields_masked_by_default(self):
        s = dataclasses.replace(Settings(), SECRET_KEY="my-super-secret")
        d = s.as_dict()
        assert d["SECRET_KEY"] == "***"

    def test_sensitive_fields_unmasked_when_flag_false(self):
        s = dataclasses.replace(Settings(), SECRET_KEY="my-super-secret")
        d = s.as_dict(mask_sensitive=False)
        assert d["SECRET_KEY"] == "my-super-secret"

    def test_non_sensitive_field_not_masked(self):
        s = Settings()
        d = s.as_dict()
        assert d["DEBUG"] == s.DEBUG


# ---------------------------------------------------------------------------
# Cast helpers
# ---------------------------------------------------------------------------


class TestCastBool:
    def test_true_values(self):
        for v in ("1", "true", "yes", "on", "TRUE", "Yes"):
            assert _cast_bool(v) is True

    def test_false_values(self):
        for v in ("0", "false", "no", "off", "FALSE"):
            assert _cast_bool(v) is False


class TestCastTuple:
    def test_comma_separated(self):
        assert _cast_tuple("a,b,c") == ("a", "b", "c")

    def test_strips_whitespace(self):
        assert _cast_tuple(" a , b ") == ("a", "b")

    def test_empty_string_returns_empty(self):
        assert _cast_tuple("") == ()


class TestCastTimedelta:
    def test_seconds_to_timedelta(self):
        assert _cast_timedelta("3600") == timedelta(seconds=3600)

    def test_zero(self):
        assert _cast_timedelta("0") == timedelta(0)


class TestCastEnvValue:
    def test_bool_cast(self):
        s = Settings()
        result = _cast_env_value(s.DEBUG, "false")
        assert result is False

    def test_int_cast(self):
        s = Settings()
        result = _cast_env_value(s.DATABASE_POOL_SIZE, "20")
        assert result == 20

    def test_str_cast(self):
        s = Settings()
        result = _cast_env_value(s.TIME_ZONE, "America/New_York")
        assert result == "America/New_York"

    def test_unsupported_type_returns_none(self):
        # dict fields cannot be overridden via env var
        s = Settings()
        result = _cast_env_value(s.CACHES, '{"key": "val"}')
        assert result is None


# ---------------------------------------------------------------------------
# _auto_include_project_app
# ---------------------------------------------------------------------------


class TestAutoIncludeProjectApp:
    def test_prepends_project_app_when_absent(self):
        s = Settings()
        result = _auto_include_project_app(s, "myproject.settings")
        assert result.INSTALLED_APPS[0] == "myproject"

    def test_does_not_duplicate_if_already_present(self):
        s = dataclasses.replace(Settings(), INSTALLED_APPS=("myproject",))
        result = _auto_include_project_app(s, "myproject.settings")
        assert result.INSTALLED_APPS.count("myproject") == 1

    def test_empty_module_path_returns_unchanged(self):
        s = Settings()
        result = _auto_include_project_app(s, "")
        assert result is s


# ---------------------------------------------------------------------------
# _apply_env_overrides
# ---------------------------------------------------------------------------


class TestApplyEnvOverrides:
    def test_applies_bool_override(self, monkeypatch):
        monkeypatch.setenv("DEBUG", "false")
        s = Settings()
        result = _apply_env_overrides(s)
        assert result.DEBUG is False

    def test_applies_int_override(self, monkeypatch):
        monkeypatch.setenv("DATABASE_POOL_SIZE", "42")
        s = Settings()
        result = _apply_env_overrides(s)
        assert result.DATABASE_POOL_SIZE == 42

    def test_no_override_when_env_absent(self, monkeypatch):
        monkeypatch.delenv("DEBUG", raising=False)
        s = Settings()
        result = _apply_env_overrides(s)
        assert result.DEBUG == s.DEBUG


# ---------------------------------------------------------------------------
# generate_secret_key
# ---------------------------------------------------------------------------


class TestGenerateSecretKey:
    def test_returns_nonempty_string(self):
        key = generate_secret_key()
        assert isinstance(key, str)
        assert len(key) > 0

    def test_custom_length(self):
        key = generate_secret_key(length=32)
        # token_urlsafe(32) produces ~43 chars; just check it's substantial
        assert len(key) >= 32

    def test_two_calls_differ(self):
        assert generate_secret_key() != generate_secret_key()


# ---------------------------------------------------------------------------
# validate_settings
# ---------------------------------------------------------------------------


class TestValidateSettings:
    def _prod(self, **overrides):
        """Return a Settings suitable for production validation (all checks pass)."""
        base = {
            "DEBUG": False,
            "SECRET_KEY": "a" * 60,
            "SECURE_COOKIES": True,
            "ALLOWED_HOSTS": ("example.com",),
            "SECURE_SSL_REDIRECT": True,
            "SECURE_HSTS_SECONDS": 31536000,
            "SESSION_COOKIE_SECURE": True,
            "CSRF_COOKIE_SECURE": True,
            "OPENAPI_ENABLED": False,
            "CORS_ALLOWED_HEADERS": ("content-type",),
            "DATABASE_URL": "postgres://localhost/db",
        }
        base.update(overrides)
        return dataclasses.replace(Settings(), **base)

    def test_valid_production_settings_passes(self):
        validate_settings(self._prod(), "production")  # must not raise

    def test_debug_true_in_production_fails(self):
        s = self._prod(DEBUG=True)
        with pytest.raises(SettingsValidationError, match="DEBUG"):
            validate_settings(s, "production")

    def test_missing_secret_key_in_production_fails(self):
        s = self._prod(SECRET_KEY="")
        with pytest.raises(SettingsValidationError, match="SECRET_KEY"):
            validate_settings(s, "production")

    def test_short_secret_key_in_production_fails(self):
        s = self._prod(SECRET_KEY="short")
        with pytest.raises(SettingsValidationError, match="SECRET_KEY"):
            validate_settings(s, "production")

    def test_missing_database_url_fails(self):
        s = dataclasses.replace(Settings(), DATABASE_URL="")
        with pytest.raises(SettingsValidationError, match="DATABASE_URL"):
            validate_settings(s, "development")

    def test_insecure_jwt_algorithm_fails(self):
        s = dataclasses.replace(Settings(), JWT_ALGORITHM="none", DATABASE_URL="sqlite:///x")
        with pytest.raises(SettingsValidationError, match="JWT_ALGORITHM"):
            validate_settings(s, "development")

    def test_openapi_enabled_in_production_fails(self):
        s = self._prod(OPENAPI_ENABLED=True)
        with pytest.raises(SettingsValidationError, match="OPENAPI_ENABLED"):
            validate_settings(s, "production")

    def test_wildcard_cors_headers_in_production_fails(self):
        s = self._prod(CORS_ALLOWED_HEADERS=("*",))
        with pytest.raises(SettingsValidationError, match="CORS_ALLOWED_HEADERS"):
            validate_settings(s, "production")

    def test_multiple_errors_raised_together(self):
        s = self._prod(DEBUG=True, OPENAPI_ENABLED=True)
        with pytest.raises(SettingsValidationError) as exc_info:
            validate_settings(s, "production")
        assert len(exc_info.value.errors) >= 2

    def test_setup_uses_custom_settings_module(self, monkeypatch, tmp_path):
        """_setup loads a custom Settings subclass from OPENVIPER_SETTINGS_MODULE."""
        settings_file = tmp_path / "custom_settings.py"
        settings_file.write_text("""
import dataclasses
from openviper.conf import Settings

@dataclasses.dataclass(frozen=True)
class CustomSettings(Settings):
    DEBUG: bool = False
    PROJECT_NAME: str = "CustomProject"
""")

        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setenv("OPENVIPER_SETTINGS_MODULE", "custom_settings")

        settings_mod = sys.modules["openviper.conf.settings"]
        settings_mod._MODULE_CACHE.clear()
        settings_mod._SETTINGS_CLASS_CACHE.clear()

        lazy = _LazySettings()
        lazy._setup()
        assert lazy._instance.DEBUG is False
        assert lazy._instance.PROJECT_NAME == "CustomProject"

    def test_setup_uses_cached_settings_class(self, monkeypatch, tmp_path):
        """_setup uses cached Settings class on second load."""
        settings_file = tmp_path / "cached_settings.py"
        settings_file.write_text("""
import dataclasses
from openviper.conf import Settings

@dataclasses.dataclass(frozen=True)
class CachedSettings(Settings):
    PROJECT_NAME: str = "Cached"
""")

        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setenv("OPENVIPER_SETTINGS_MODULE", "cached_settings")

        # Clear caches
        settings_mod = sys.modules["openviper.conf.settings"]
        settings_mod._MODULE_CACHE.clear()
        settings_mod._SETTINGS_CLASS_CACHE.clear()

        # First load
        lazy1 = _LazySettings()
        lazy1._setup()
        assert "cached_settings" in settings_mod._SETTINGS_CLASS_CACHE

        # Second load should use cache
        lazy2 = _LazySettings()
        lazy2._setup()
        assert lazy2._instance.PROJECT_NAME == "Cached"

    def test_setup_import_error_raises(self, monkeypatch):
        """_setup raises RuntimeError when the settings module cannot be imported."""
        monkeypatch.setenv("OPENVIPER_SETTINGS_MODULE", "nonexistent_module")

        # Clear caches
        settings_mod = sys.modules["openviper.conf.settings"]
        settings_mod._MODULE_CACHE.clear()
        settings_mod._SETTINGS_CLASS_CACHE.clear()

        lazy = _LazySettings()
        with pytest.raises(RuntimeError, match="Could not import"):
            lazy._setup()

    def test_setup_no_settings_subclass_raises(self, monkeypatch, tmp_path):
        """_setup raises RuntimeError when module has no Settings subclass."""
        settings_file = tmp_path / "no_subclass.py"
        settings_file.write_text("""
# No Settings subclass here
DEBUG = True
""")

        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setenv("OPENVIPER_SETTINGS_MODULE", "no_subclass")

        # Clear caches
        settings_mod = sys.modules["openviper.conf.settings"]
        settings_mod._MODULE_CACHE.clear()
        settings_mod._SETTINGS_CLASS_CACHE.clear()

        lazy = _LazySettings()
        with pytest.raises(RuntimeError, match="contains no Settings subclass"):
            lazy._setup()

    def test_setup_auto_generates_secret_key_for_development(self, monkeypatch):
        """_setup auto-generates SECRET_KEY for development/test."""
        monkeypatch.setenv("OPENVIPER_SETTINGS_MODULE", "")
        monkeypatch.setenv("OPENVIPER_ENV", "development")
        monkeypatch.delenv("SECRET_KEY", raising=False)

        lazy = _LazySettings()
        lazy._setup()

        # SECRET_KEY should be auto-generated (not empty)
        assert lazy._instance.SECRET_KEY != ""
        assert len(lazy._instance.SECRET_KEY) > 40

    def test_setup_does_not_generate_secret_key_for_production(self, monkeypatch):
        """_setup does not auto-generate SECRET_KEY for production."""
        monkeypatch.setenv("OPENVIPER_SETTINGS_MODULE", "")
        monkeypatch.setenv("OPENVIPER_ENV", "production")
        monkeypatch.delenv("SECRET_KEY", raising=False)

        lazy = _LazySettings()
        lazy._setup()

        # SECRET_KEY remains empty in production
        assert lazy._instance.SECRET_KEY == ""

    def test_setup_replaces_insecure_change_me_in_dev(self, monkeypatch, tmp_path):
        """_setup replaces INSECURE-CHANGE-ME in development."""
        monkeypatch.delenv("SECRET_KEY", raising=False)
        settings_file = tmp_path / "insecure_settings.py"
        settings_file.write_text("""
import dataclasses
from openviper.conf import Settings

@dataclasses.dataclass(frozen=True)
class InsecureSettings(Settings):
    SECRET_KEY: str = "INSECURE-CHANGE-ME"
""")

        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setenv("OPENVIPER_SETTINGS_MODULE", "insecure_settings")
        monkeypatch.setenv("OPENVIPER_ENV", "development")

        # Clear caches
        settings_mod = sys.modules["openviper.conf.settings"]
        settings_mod._MODULE_CACHE.clear()
        settings_mod._SETTINGS_CLASS_CACHE.clear()

        lazy = _LazySettings()
        lazy._setup()

        assert lazy._instance.SECRET_KEY != "INSECURE-CHANGE-ME"
        assert len(lazy._instance.SECRET_KEY) > 40

    def test_setup_auto_includes_project_app(self, monkeypatch, tmp_path):
        """_setup auto-prepends project app to INSTALLED_APPS."""
        settings_file = tmp_path / "myproject" / "settings.py"
        settings_file.parent.mkdir()
        settings_file.write_text("""
import dataclasses
from openviper.conf import Settings

@dataclasses.dataclass(frozen=True)
class MyProjectSettings(Settings):
    pass
""")

        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setenv("OPENVIPER_SETTINGS_MODULE", "myproject.settings")

        settings_mod = sys.modules["openviper.conf.settings"]
        settings_mod._MODULE_CACHE.clear()
        settings_mod._SETTINGS_CLASS_CACHE.clear()

        lazy = _LazySettings()
        lazy._setup()

        assert "myproject" in lazy._instance.INSTALLED_APPS


# ---------------------------------------------------------------------------
# configure_logging
# ---------------------------------------------------------------------------


class TestConfigureLogging:
    """Tests for configure_logging and _JsonFormatter."""

    def setup_method(self) -> None:
        ov = logging.getLogger("openviper")
        ov.handlers = [h for h in ov.handlers if not isinstance(h, _OVDefaultHandler)]
        ov.setLevel(logging.NOTSET)
        ov.propagate = True

    def teardown_method(self) -> None:
        ov = logging.getLogger("openviper")
        ov.handlers = [h for h in ov.handlers if not isinstance(h, _OVDefaultHandler)]
        ov.propagate = True

    def test_text_format_installs_handler_on_openviper_logger(self) -> None:
        s = Settings(LOG_LEVEL="DEBUG", LOG_FORMAT="text")
        configure_logging(s)
        ov = logging.getLogger("openviper")
        assert any(isinstance(h, _OVDefaultHandler) for h in ov.handlers)

    def test_log_level_applied_to_openviper_logger(self) -> None:
        s = Settings(LOG_LEVEL="WARNING", LOG_FORMAT="text")
        configure_logging(s)
        assert logging.getLogger("openviper").level == logging.WARNING

    def test_json_format_uses_json_formatter(self) -> None:
        s = Settings(LOG_LEVEL="INFO", LOG_FORMAT="json")
        configure_logging(s)
        ov = logging.getLogger("openviper")
        assert any(
            isinstance(h, _OVDefaultHandler) and isinstance(h.formatter, _JsonFormatter)
            for h in ov.handlers
        )

    def test_propagate_remains_true(self) -> None:
        s = Settings(LOG_LEVEL="INFO", LOG_FORMAT="text")
        configure_logging(s)
        assert logging.getLogger("openviper").propagate is True

    def test_repeated_calls_do_not_duplicate_handlers(self) -> None:
        s = Settings(LOG_LEVEL="INFO", LOG_FORMAT="text")
        configure_logging(s)
        configure_logging(s)
        ov_default = [
            h for h in logging.getLogger("openviper").handlers if isinstance(h, _OVDefaultHandler)
        ]
        assert len(ov_default) == 1

    def test_logging_dict_calls_dictconfig(self) -> None:
        config: dict = {
            "version": 1,
            "disable_existing_loggers": False,
            "handlers": {
                "null": {"class": "logging.NullHandler"},
            },
            "loggers": {
                "openviper": {"handlers": ["null"], "level": "CRITICAL", "propagate": False},
            },
        }
        s = Settings(LOGGING=config)
        configure_logging(s)
        assert logging.getLogger("openviper").level == logging.CRITICAL

    def test_json_formatter_produces_valid_json(self) -> None:
        formatter = _JsonFormatter()
        record = logging.LogRecord(
            name="openviper.test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello world",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "openviper.test"
        assert parsed["message"] == "hello world"
        assert "time" in parsed
