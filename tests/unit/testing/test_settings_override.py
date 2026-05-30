"""Tests for OpenViper test settings override helpers."""

from __future__ import annotations

import os.path as _osp

import pytest

from openviper.conf import settings
from openviper.testing.settings import (
    OpenViperTestingConfigError,
    as_bool,
    as_database_isolation,
    as_mapping,
    as_optional_string,
    import_from_path,
    override_openviper_settings,
)


def test_override_settings_applies_value_within_context() -> None:
    original = settings.DEBUG

    with override_openviper_settings(DEBUG=not original):
        assert settings.DEBUG is not original


def test_override_settings_restores_original_after_context() -> None:
    original = settings.DEBUG

    with override_openviper_settings(DEBUG=not original):
        pass

    assert settings.DEBUG is original


def test_override_settings_restores_after_exception_in_context() -> None:
    original = settings.DEBUG

    with pytest.raises(RuntimeError):
        with override_openviper_settings(DEBUG=not original):
            raise RuntimeError("simulated failure")

    assert settings.DEBUG is original


def test_override_settings_rejects_unknown_setting_name() -> None:
    with pytest.raises(OpenViperTestingConfigError, match="Unknown"):
        with override_openviper_settings(THIS_SETTING_DOES_NOT_EXIST=True):
            pass  # pragma: no cover


def test_override_settings_supports_nested_overrides() -> None:
    outer_debug = not settings.DEBUG
    inner_debug = settings.DEBUG  # flip back

    with override_openviper_settings(DEBUG=outer_debug):
        assert settings.DEBUG is outer_debug

        with override_openviper_settings(DEBUG=inner_debug):
            assert settings.DEBUG is inner_debug

        assert settings.DEBUG is outer_debug


def test_as_bool_returns_true_for_true() -> None:
    assert as_bool(True, False) is True


def test_as_bool_returns_false_for_false() -> None:
    assert as_bool(False, True) is False


def test_as_bool_falls_back_to_default_for_non_bool() -> None:
    assert as_bool("yes", True) is True
    assert as_bool(None, False) is False


def test_as_optional_string_returns_none_for_blank() -> None:
    assert as_optional_string("") is None
    assert as_optional_string("   ") is None
    assert as_optional_string(None) is None


def test_as_optional_string_strips_whitespace() -> None:
    assert as_optional_string("  myapp  ") == "myapp"


def test_as_mapping_returns_empty_for_non_dict() -> None:
    assert as_mapping(None) == {}
    assert as_mapping("string") == {}
    assert as_mapping(42) == {}


def test_as_mapping_returns_the_dict_unchanged() -> None:
    data = {"a": 1, "b": 2}
    assert as_mapping(data) is data


def test_as_database_isolation_returns_transaction_for_none() -> None:
    assert as_database_isolation(None) == "transaction"


def test_as_database_isolation_accepts_all_valid_modes() -> None:
    for mode in ("transaction", "truncate", "recreate", "in_memory"):
        assert as_database_isolation(mode) == mode


def test_as_database_isolation_rejects_invalid_value() -> None:
    with pytest.raises(OpenViperTestingConfigError, match="database_isolation"):
        as_database_isolation("unknown_mode")


def test_import_from_path_loads_stdlib_attribute() -> None:
    result = import_from_path("os.path:join")

    assert result is _osp.join


def test_import_from_path_supports_dot_separated_path() -> None:
    result = import_from_path("os.path.join")

    assert result is _osp.join


def test_import_from_path_raises_for_invalid_format() -> None:
    with pytest.raises(OpenViperTestingConfigError, match="Invalid import path"):
        import_from_path("nocolon")


def test_import_from_path_raises_for_nonexistent_module() -> None:
    with pytest.raises(OpenViperTestingConfigError, match="Could not import"):
        import_from_path("nonexistent.module:attr")


def test_import_from_path_raises_for_missing_attribute() -> None:
    with pytest.raises(OpenViperTestingConfigError, match="no attribute"):
        import_from_path("os.path:nonexistent_function")
