"""Unit tests for openviper.staticfiles (the package __init__ module).

Covers the four public functions:
    static()            – sets _static_serving_enabled flag, returns []
    is_static_enabled() – reads the flag
    media()             – sets _media_serving_enabled flag, returns []
    is_media_enabled()  – reads the flag

The missing coverage lines (41-42, 64-65) are the bodies of static() and
media() respectively.  Each test that calls those functions covers those lines.
"""

from __future__ import annotations

import pytest

import openviper.staticfiles as sf_module
from openviper.staticfiles import is_media_enabled, is_static_enabled, media, static

# ── Fixture ───────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_serving_flags():
    """Reset both module-level flags before (and after) every test."""
    sf_module._static_serving_enabled = False
    sf_module._media_serving_enabled = False
    yield
    sf_module._static_serving_enabled = False
    sf_module._media_serving_enabled = False


# ── is_static_enabled / static() ─────────────────────────────────────────────


def test_is_static_enabled_is_false_initially():
    assert is_static_enabled() is False


def test_static_returns_empty_list():
    result = static()
    assert result == []


def test_static_return_type_is_list():
    assert isinstance(static(), list)


def test_static_sets_enabled_flag():
    assert is_static_enabled() is False
    static()
    assert is_static_enabled() is True


def test_calling_static_twice_stays_enabled():
    static()
    static()
    assert is_static_enabled() is True


def test_static_sets_module_level_variable():
    static()
    assert sf_module._static_serving_enabled is True


def test_is_static_enabled_reflects_module_variable():
    sf_module._static_serving_enabled = True
    assert is_static_enabled() is True


# ── is_media_enabled / media() ────────────────────────────────────────────────


def test_is_media_enabled_is_false_initially():
    assert is_media_enabled() is False


def test_media_returns_empty_list():
    result = media()
    assert result == []


def test_media_return_type_is_list():
    assert isinstance(media(), list)


def test_media_sets_enabled_flag():
    assert is_media_enabled() is False
    media()
    assert is_media_enabled() is True


def test_calling_media_twice_stays_enabled():
    media()
    media()
    assert is_media_enabled() is True


def test_media_sets_module_level_variable():
    media()
    assert sf_module._media_serving_enabled is True


def test_is_media_enabled_reflects_module_variable():
    sf_module._media_serving_enabled = True
    assert is_media_enabled() is True


# ── Independence between static and media ────────────────────────────────────


def test_static_does_not_affect_media_flag():
    static()
    assert is_static_enabled() is True
    assert is_media_enabled() is False


def test_media_does_not_affect_static_flag():
    media()
    assert is_media_enabled() is True
    assert is_static_enabled() is False


def test_both_can_be_enabled_simultaneously():
    static()
    media()
    assert is_static_enabled() is True
    assert is_media_enabled() is True


# ── Integration with route_paths pattern ─────────────────────────────────────


def test_static_can_be_appended_to_route_list():
    routes = [("/", "router")]
    combined = routes + static()
    assert combined == [("/", "router")]
    assert is_static_enabled() is True


def test_media_can_be_appended_to_route_list():
    routes = [("/", "router")]
    combined = routes + media()
    assert combined == [("/", "router")]
    assert is_media_enabled() is True


def test_static_and_media_chained_with_route_list():
    routes = [("/", "router")]
    combined = routes + static() + media()
    assert combined == [("/", "router")]
    assert is_static_enabled() is True
    assert is_media_enabled() is True


# ── __all__ exports ───────────────────────────────────────────────────────────


def test_all_exports_present():
    expected = {
        "StaticFilesMiddleware",
        "collect_static",
        "static",
        "media",
        "is_static_enabled",
        "is_media_enabled",
    }
    assert expected.issubset(set(sf_module.__all__))
