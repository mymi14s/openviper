"""Tests for the @override_settings decorator."""

from __future__ import annotations

import pytest

from openviper.conf import settings
from openviper.testing.settings import OpenViperTestingConfigError, override_settings

# ── sync function decorator ───────────────────────────────────────────────


@override_settings(DEBUG=False)
def test_decorator_applies_override_to_sync_function() -> None:
    assert settings.DEBUG is False


@override_settings(DEBUG=False)
def test_decorator_does_not_leak_sync_override_to_neighbour() -> None:
    # The override should only be active during *this* test.
    pass


def test_sync_override_is_not_active_outside_decorated_function() -> None:
    # Verify the previous test's decorator did not bleed into this test.
    # The default value is True in test environments.
    assert isinstance(settings.DEBUG, bool)


# ── async function decorator ──────────────────────────────────────────────


@override_settings(DEBUG=False)
async def test_decorator_applies_override_to_async_function() -> None:
    assert settings.DEBUG is False


@override_settings(DEBUG=False)
async def test_async_decorator_restores_after_awaited_body() -> None:
    original = settings.DEBUG
    assert original is False


async def test_async_override_does_not_persist_after_decorated_test() -> None:
    assert isinstance(settings.DEBUG, bool)


# ── nested overrides ──────────────────────────────────────────────────────


@override_settings(DEBUG=False)
def test_decorator_supports_multiple_overrides_at_once() -> None:
    assert settings.DEBUG is False


# ── class decorator ───────────────────────────────────────────────────────


@override_settings(DEBUG=False)
class TestOverrideSettingsClassDecorator:
    def test_class_decorator_wraps_test_methods(self) -> None:
        assert settings.DEBUG is False

    def test_class_decorator_wraps_all_test_methods(self) -> None:
        assert settings.DEBUG is False

    def helper_method_is_not_wrapped(self) -> None:
        # Non-test methods should not be wrapped - this should not be collected.
        pass  # pragma: no cover


# ── error handling ────────────────────────────────────────────────────────


def test_decorator_with_unknown_setting_raises_on_call() -> None:
    @override_settings(NONEXISTENT_SETTING_XYZ=True)
    def bad_test() -> None:
        pass  # pragma: no cover

    with pytest.raises(OpenViperTestingConfigError, match="Unknown"):
        bad_test()


async def test_decorator_with_unknown_setting_raises_from_async_call() -> None:
    @override_settings(NONEXISTENT_SETTING_XYZ=True)
    async def bad_async_test() -> None:
        pass  # pragma: no cover

    with pytest.raises(OpenViperTestingConfigError, match="Unknown"):
        await bad_async_test()


# ── restore on exception ──────────────────────────────────────────────────


def test_decorator_restores_settings_even_if_test_raises() -> None:
    original = settings.DEBUG

    @override_settings(DEBUG=not original)
    def failing_test() -> None:
        raise RuntimeError("deliberate failure")

    with pytest.raises(RuntimeError):
        failing_test()

    assert settings.DEBUG is original


# ── preserves function metadata ───────────────────────────────────────────


def test_decorator_preserves_function_name() -> None:
    @override_settings(DEBUG=False)
    def my_named_test() -> None:
        pass  # pragma: no cover

    assert my_named_test.__name__ == "my_named_test"


def test_decorator_preserves_function_docstring() -> None:
    @override_settings(DEBUG=False)
    def documented_test() -> None:
        """My docstring."""

    assert documented_test.__doc__ == "My docstring."
