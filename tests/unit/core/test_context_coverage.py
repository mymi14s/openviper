"""Coverage for openviper/core/context.py – get_current_user()."""

from __future__ import annotations

from openviper.core.context import current_user, get_current_user, set_current_user


def test_get_current_user_returns_none_when_unset():
    """get_current_user() returns None when no user is set in context."""
    # Confirm we are outside any request context
    token = current_user.set(None)
    try:
        assert get_current_user() is None
    finally:
        current_user.reset(token)


def test_get_current_user_returns_set_value():
    """get_current_user() returns the value placed by set_current_user()."""
    sentinel = object()
    token = set_current_user(sentinel)
    try:
        assert get_current_user() is sentinel
    finally:
        current_user.reset(token)
