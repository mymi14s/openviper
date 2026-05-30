"""Request-scoped storage helpers for authentication internals."""

from __future__ import annotations

from collections.abc import MutableMapping

AUTH_STATE_KEY = "openviper.auth"


def auth_state(request: object) -> dict[str, object]:
    """Return a mutable auth state mapping bound to one request."""
    state = getattr(request, "state", None)
    if isinstance(state, dict):
        auth_data = state.setdefault(AUTH_STATE_KEY, {})
        if isinstance(auth_data, dict):
            return auth_data

    scope = getattr(request, "_scope", None)
    if isinstance(scope, MutableMapping):
        auth_data = scope.setdefault(AUTH_STATE_KEY, {})
        if isinstance(auth_data, dict):
            return auth_data

    return {}


def get_auth_state(request: object, key: str, default: object = None) -> object:
    """Return an auth state value for *request*."""
    value = auth_state(request).get(key, default)
    if value is not default:
        return value
    legacy_name = f"_auth_{key}"
    return getattr(request, legacy_name, default)


def set_auth_state(request: object, key: str, value: object) -> None:
    """Set an auth state value for *request*."""
    auth_state(request)[key] = value
