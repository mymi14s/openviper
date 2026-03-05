"""Tests for openviper.conf.settings — frozen-dataclass rewrite.

Settings are now an immutable frozen dataclass; this module tests:
- ``Settings`` value object behaviour (as_dict, __getitem__)
- ``_LazySettings`` configure / _setup / __setattr__ invariants
- validate_settings / generate_secret_key helpers
- env-var override casting (_apply_env_overrides)
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from openviper.conf.settings import (
    Settings,
    _apply_env_overrides,
    _LazySettings,
    generate_secret_key,
    validate_settings,
)
from openviper.exceptions import SettingsValidationError

# ---------------------------------------------------------------------------
# Settings dataclass behaviour
# ---------------------------------------------------------------------------


def test_settings_defaults():
    s = Settings()
    assert s.DEBUG is True
    assert s.PROJECT_NAME == "OpenViper Application"
    assert isinstance(s.ALLOWED_HOSTS, tuple)


def test_settings_as_dict():
    s = Settings()
    d = s.as_dict()
    assert isinstance(d, dict)
    assert "DEBUG" in d
    assert "PROJECT_NAME" in d
    assert d["DEBUG"] is True


def test_settings_getitem():
    s = Settings()
    assert s["DEBUG"] is True
    assert s["PROJECT_NAME"] == "OpenViper Application"


def test_settings_frozen():
    """Mutation of a frozen dataclass must raise FrozenInstanceError."""
    s = Settings()
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        s.DEBUG = False  # type: ignore[misc]


def test_settings_subclass_with_custom_field():
    @dataclasses.dataclass(frozen=True)
    class MySettings(Settings):
        MY_KEY: str = "hello"

    s = MySettings()
    assert s.MY_KEY == "hello"
    assert s.DEBUG is True  # inherits default

    d = s.as_dict()
    assert d["MY_KEY"] == "hello"


# ---------------------------------------------------------------------------
# validate_settings
# ---------------------------------------------------------------------------


def test_validate_settings_success_development():
    s = dataclasses.replace(Settings(), DATABASE_URL="sqlite:///:memory:")
    # Should not raise
    validate_settings(s, "development")


def test_validate_settings_missing_db():
    s = Settings()
    with pytest.raises(SettingsValidationError, match="DATABASE_URL must be set"):
        validate_settings(s, "development")


def test_validate_settings_production_debug():
    s = dataclasses.replace(
        Settings(),
        DATABASE_URL="postgresql://x",
        DEBUG=True,
        SECRET_KEY="a" * 60,
        SECURE_COOKIES=True,
        ALLOWED_HOSTS=("example.com",),
    )
    with pytest.raises(SettingsValidationError) as exc_info:
        validate_settings(s, "production")
    assert "DEBUG must be False" in str(exc_info.value)


def test_validate_settings_production_weak_secret_key():
    s = dataclasses.replace(
        Settings(),
        DATABASE_URL="postgresql://x",
        DEBUG=False,
        SECRET_KEY="dev-insecure-key",
        SECURE_COOKIES=True,
        ALLOWED_HOSTS=("example.com",),
    )
    with pytest.raises(SettingsValidationError) as exc_info:
        validate_settings(s, "production")
    assert "SECRET_KEY must be set to a strong random value" in str(exc_info.value)


def test_validate_settings_production_short_secret_key():
    s = dataclasses.replace(
        Settings(),
        DATABASE_URL="postgresql://x",
        DEBUG=False,
        SECRET_KEY="short-but-not-default",
        SECURE_COOKIES=True,
        ALLOWED_HOSTS=("example.com",),
    )
    with pytest.raises(SettingsValidationError) as exc_info:
        validate_settings(s, "production")
    assert "SECRET_KEY must be at least 50 characters" in str(exc_info.value)


def test_validate_settings_production_insecure_cookies():
    s = dataclasses.replace(
        Settings(),
        DATABASE_URL="postgresql://x",
        DEBUG=False,
        SECRET_KEY="a" * 60,
        SECURE_COOKIES=False,
        ALLOWED_HOSTS=("example.com",),
    )
    with pytest.raises(SettingsValidationError) as exc_info:
        validate_settings(s, "production")
    assert "SECURE_COOKIES must be True" in str(exc_info.value)


def test_validate_settings_production_empty_allowed_hosts():
    s = dataclasses.replace(
        Settings(),
        DATABASE_URL="postgresql://x",
        DEBUG=False,
        SECRET_KEY="a" * 60,
        SECURE_COOKIES=True,
        ALLOWED_HOSTS=(),
    )
    with pytest.raises(SettingsValidationError) as exc_info:
        validate_settings(s, "production")
    assert "ALLOWED_HOSTS" in str(exc_info.value)


# ---------------------------------------------------------------------------
# generate_secret_key
# ---------------------------------------------------------------------------


def test_generate_secret_key_returns_string():
    key = generate_secret_key(64)
    assert isinstance(key, str)


def test_generate_secret_key_is_long_enough():
    key = generate_secret_key(64)
    # url-safe base64 output is longer than the byte length
    assert len(key) >= 64


def test_generate_secret_key_is_unique():
    assert generate_secret_key() != generate_secret_key()


# ---------------------------------------------------------------------------
# _apply_env_overrides
# ---------------------------------------------------------------------------


def test_apply_env_overrides_bool():
    s = Settings()
    with patch.dict("os.environ", {"DEBUG": "0"}):
        result = _apply_env_overrides(s)
    assert result.DEBUG is False


def test_apply_env_overrides_int():
    s = Settings()
    with patch.dict("os.environ", {"DATABASE_POOL_SIZE": "20"}):
        result = _apply_env_overrides(s)
    assert result.DATABASE_POOL_SIZE == 20


def test_apply_env_overrides_float():
    s = Settings()
    with patch.dict("os.environ", {"SENTRY_SAMPLE_RATE": "0.5"}):
        result = _apply_env_overrides(s)
    assert result.SENTRY_SAMPLE_RATE == 0.5


def test_apply_env_overrides_tuple():
    s = Settings()
    with patch.dict("os.environ", {"ALLOWED_HOSTS": "a.com, b.com"}):
        result = _apply_env_overrides(s)
    assert result.ALLOWED_HOSTS == ("a.com", "b.com")


def test_apply_env_overrides_timedelta():
    s = Settings()
    with patch.dict("os.environ", {"SESSION_TIMEOUT": "7200"}):
        result = _apply_env_overrides(s)
    assert timedelta(seconds=7200) == result.SESSION_TIMEOUT


def test_apply_env_overrides_invalid_cast_ignored():
    """An env var that cannot be cast is silently skipped; default is preserved."""
    s = Settings()
    with patch.dict("os.environ", {"DATABASE_POOL_SIZE": "not_a_number"}):
        result = _apply_env_overrides(s)
    assert result.DATABASE_POOL_SIZE == 5  # default


def test_apply_env_overrides_unknown_env_var_ignored():
    """An env var that has no corresponding Settings field is not applied."""
    s = Settings()
    with patch.dict("os.environ", {"TOTALLY_UNKNOWN_VAR_XYZ": "hello"}):
        result = _apply_env_overrides(s)
    assert not hasattr(result, "TOTALLY_UNKNOWN_VAR_XYZ")


def test_apply_env_overrides_returns_new_instance():
    s = Settings()
    with patch.dict("os.environ", {"DEBUG": "0"}):
        result = _apply_env_overrides(s)
    assert result is not s


def test_apply_env_overrides_no_overrides_returns_same():
    s = Settings()
    with patch.dict("os.environ", {}, clear=True):
        result = _apply_env_overrides(s)
    assert result is s


# ---------------------------------------------------------------------------
# _LazySettings
# ---------------------------------------------------------------------------


def test_lazy_settings_setup_loads_defaults():
    lazy = _LazySettings()
    lazy._setup()
    assert lazy._configured is True
    assert isinstance(lazy._instance, Settings)


def test_lazy_settings_getattr_triggers_setup():
    lazy = _LazySettings()
    assert lazy.DEBUG is True
    assert lazy._configured is True


def test_lazy_settings_setattr_raises_after_configured():
    """Non-underscore attribute writes raise AttributeError once configured."""
    lazy = _LazySettings()
    lazy._setup()  # trigger configuration
    with pytest.raises(AttributeError, match="read-only"):
        lazy.DEBUG = False  # type: ignore[misc]


def test_lazy_settings_configure_accepts_settings_object():
    lazy = _LazySettings()

    @dataclasses.dataclass(frozen=True)
    class CustomSettings(Settings):
        PROJECT_NAME: str = "MyProject"

    lazy.configure(CustomSettings())
    assert lazy.PROJECT_NAME == "MyProject"


def test_lazy_settings_configure_raises_on_second_call():
    lazy = _LazySettings()

    lazy.configure(Settings())
    with pytest.raises(RuntimeError, match="configure\\(\\) called more than once"):
        lazy.configure(Settings())


def test_lazy_settings_configure_before_setup():
    lazy = _LazySettings()

    @dataclasses.dataclass(frozen=True)
    class App(Settings):
        MY_FIELD: str = "value"

    lazy.configure(App())
    assert lazy.MY_FIELD == "value"


def test_lazy_settings_module_load():
    lazy = _LazySettings()

    fake_mod = MagicMock()

    @dataclasses.dataclass(frozen=True)
    class FakeSettings(Settings):
        CUSTOM_VAR: int = 123

    fake_mod.FakeSettings = FakeSettings

    with (
        patch.dict("sys.modules", {"my_fake_settings": fake_mod}),
        patch.dict("os.environ", {"OPENVIPER_SETTINGS_MODULE": "my_fake_settings"}),
    ):
        lazy._setup()
        assert lazy.CUSTOM_VAR == 123
        # Top-level package auto-included in INSTALLED_APPS
        assert "my_fake_settings" in lazy.INSTALLED_APPS


def test_lazy_settings_module_load_no_settings_class_falls_back_to_defaults():
    lazy = _LazySettings()
    fake_mod = MagicMock(spec=[])  # no Settings subclass exposed

    with (
        patch.dict("sys.modules", {"mod_with_no_settings": fake_mod}),
        patch.dict("os.environ", {"OPENVIPER_SETTINGS_MODULE": "mod_with_no_settings"}),
    ):
        lazy._setup()
    assert isinstance(lazy._instance, Settings)


def test_lazy_settings_already_configured_skips_setup():
    lazy = _LazySettings()
    lazy.configure(Settings())
    assert lazy._configured is True
    lazy._setup()  # must not raise or change instance
    assert isinstance(lazy._instance, Settings)


def test_lazy_settings_no_dotenv():
    import importlib
    import sys

    with patch.dict("sys.modules", {"dotenv": None}):
        mod = importlib.reload(sys.modules["openviper.conf.settings"])
        assert not mod._HAS_DOTENV
    importlib.reload(sys.modules["openviper.conf.settings"])
