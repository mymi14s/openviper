import asyncio

import pytest

from openviper.utils.translation import LazyString, get_language, gettext, set_language
from openviper.utils.translation import gettext_lazy as _


def test_immediate_translation():
    """Verify gettext returns the message when no translation file exists."""
    set_language("en")
    assert gettext("Hello") == "Hello"

    set_language("fr")
    # Without an actual .mo file, it should just return the message
    assert gettext("Hello") == "Hello"


def test_lazy_translation_deferred():
    """Verify gettext_lazy returns a LazyString that translates on evaluation."""
    set_language("en")
    lazy_msg = _("Hello")
    assert isinstance(lazy_msg, LazyString)
    assert str(lazy_msg) == "Hello"


def test_lazy_translation_switches_with_context():
    """Verify LazyString reflects the current active language when evaluated."""
    msg = _("Welcome")

    set_language("en")
    assert str(msg) == "Welcome"

    # Even though 'msg' was created when 'en' was active, switching to 'fr'
    # should reflect in the next evaluation (if translations existed).
    set_language("fr")
    # (Since we don't have .mo files, it will still be "Welcome", but let's
    # mock gettext to prove it's being called).
    from unittest.mock import patch

    with patch("openviper.utils.translation.gettext", side_effect=lambda x: f"FR: {x}"):
        assert str(msg) == "FR: Welcome"


@pytest.mark.asyncio
async def test_thread_safety_contextvars():
    """Verify set_language is isolated per context (thread/task)."""

    set_language("en")

    async def set_to_fr():
        set_language("fr")
        await asyncio.sleep(0.1)
        return get_language()

    async def set_to_de():
        set_language("de")
        await asyncio.sleep(0.1)
        return get_language()

    results = await asyncio.gather(set_to_fr(), set_to_de())

    assert results == ["fr", "de"]
    assert get_language() == "en"  # Original context remains 'en'


def test_lazy_string_operations():
    """Verify LazyString supports common string-like operations."""
    msg = _("Total")
    assert msg + ": 10" == "Total: 10"
    assert "The " + msg == "The Total"
    assert bool(msg) is True
    assert len(msg) == 5
    assert msg == "Total"
    assert f"Result: {msg}" == "Result: Total"
