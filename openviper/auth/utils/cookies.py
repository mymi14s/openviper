"""Cookie utilities for OpenViper session authentication.

All cookie value construction validates against CR/LF characters to prevent
HTTP header injection attacks.
"""

from __future__ import annotations

import os
from http.cookies import SimpleCookie

from openviper.conf import settings

CRLF_CHARS = frozenset("\r\n")


def is_safe_cookie_value(value: str) -> bool:
    """Reject cookie values containing CR or LF to prevent header injection."""
    return not any(c in CRLF_CHARS for c in value)


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
    if morsel is None:
        return None
    value = morsel.value
    if not is_safe_cookie_value(value):
        return None
    return value


def get_cookie_settings() -> dict[str, object]:
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

    Raises:
        ValueError: If the session key contains CR/LF characters.

    Example::

        response.headers["Set-Cookie"] = build_set_cookie_header("abc123")
    """
    if not is_safe_cookie_value(session_key):
        raise ValueError("Session key contains invalid characters (CR/LF)")
    cfg = get_cookie_settings()
    parts = [f"{cfg['name']}={session_key}; Path=/"]

    timeout = getattr(settings, "SESSION_TIMEOUT", None)
    if timeout is not None:
        max_age = (
            int(timeout.total_seconds()) if hasattr(timeout, "total_seconds") else int(timeout)
        )
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
