"""Cookie utilities for OpenViper session authentication."""

from __future__ import annotations

import os
from http.cookies import SimpleCookie
from typing import Any

from openviper.conf import settings


def parse_session_key(cookie_header: str) -> str | None:
    """Extract the session key from a raw ``Cookie`` header string.

    Args:
        cookie_header: Raw Cookie header value (e.g. ``"sessionid=abc123; other=val"``).

    Returns:
        The session key string, or ``None`` if the cookie is not present.
    """
    cookie_name = getattr(settings, "SESSION_COOKIE_NAME", "sessionid")
    cookie = SimpleCookie()
    cookie.load(cookie_header)
    morsel = cookie.get(cookie_name)
    return morsel.value if morsel else None


def get_cookie_settings() -> dict[str, Any]:
    """Return the configured session cookie attributes from settings.

    Returns:
        Dict with keys: ``name``, ``httponly``, ``secure``, ``samesite``.
    """
    env = os.environ.get("ENVIRONMENT", "").lower()
    is_production = env in ("production", "prod")

    return {
        "name": getattr(settings, "SESSION_COOKIE_NAME", "sessionid"),
        "httponly": getattr(settings, "SESSION_COOKIE_HTTPONLY", True),
        "secure": getattr(settings, "SESSION_COOKIE_SECURE", is_production),
        "samesite": getattr(settings, "SESSION_COOKIE_SAMESITE", "Lax"),
    }


def build_set_cookie_header(session_key: str) -> str:
    """Build the ``Set-Cookie`` header value to establish a session cookie.

    Args:
        session_key: The session key to store in the cookie.

    Returns:
        A ``Set-Cookie`` header value string.

    Example::

        response.headers["Set-Cookie"] = build_set_cookie_header("abc123")
    """
    cfg = get_cookie_settings()
    parts = [f"{cfg['name']}={session_key}; Path=/"]

    timeout = getattr(settings, "SESSION_TIMEOUT", None)
    if timeout is not None:
        max_age = int(timeout.total_seconds())
        parts.append(f"Max-Age={max_age}")

    if cfg["httponly"]:
        parts.append("HttpOnly")
    if cfg["secure"]:
        parts.append("Secure")
    if cfg["samesite"]:
        parts.append(f"SameSite={cfg['samesite']}")

    return "; ".join(parts)


def build_clear_cookie_header() -> str:
    """Build the ``Set-Cookie`` header value to clear the session cookie.

    Returns:
        A ``Set-Cookie`` header value that expires the session cookie immediately.

    Example::

        response.headers["Set-Cookie"] = build_clear_cookie_header()
    """
    cfg = get_cookie_settings()
    parts = [f"{cfg['name']}=; Path=/; Max-Age=0"]

    if cfg["httponly"]:
        parts.append("HttpOnly")
    if cfg["secure"]:
        parts.append("Secure")

    return "; ".join(parts)
