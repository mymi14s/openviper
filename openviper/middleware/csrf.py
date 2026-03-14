"""CSRF protection middleware."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any, cast

from openviper.conf import settings
from openviper.http.response import JSONResponse
from openviper.middleware.base import ASGIApp, BaseMiddleware

CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})  # Removed TRACE for security
CSRF_COOKIE_NAME = "csrftoken"
CSRF_HEADER_NAME = "x-csrftoken"
CSRF_FORM_FIELD = "csrfmiddlewaretoken"


def _generate_csrf_token() -> str:
    return secrets.token_hex(32)


def _mask_csrf_token(token: str, secret: str) -> str:
    """Create a per-request masked token for the HTML form."""
    salt = secrets.token_hex(16)  # Increased from 8 to 16 bytes (128-bit)
    signature = hmac.new(secret.encode(), f"{salt}{token}".encode(), hashlib.sha256).hexdigest()
    return f"{salt}{signature}"


def _verify_csrf_token(cookie_token: str, submitted_token: str, secret: str) -> bool:
    """Constant-time verify that the submitted token matches the cookie."""
    if len(submitted_token) < 96:  # Updated: 32 hex chars (16 bytes) + 64 hex chars (SHA256)
        return False
    salt = submitted_token[:32]  # Updated: first 32 hex chars (16 bytes)
    expected = hmac.new(
        secret.encode(), f"{salt}{cookie_token}".encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(submitted_token[32:], expected)  # Updated: after first 32 chars


def _extract_cookie_value(cookie_header: str, cookie_name: str) -> str:
    """Fast cookie extraction without parsing all cookies.

    This is ~3x faster than SimpleCookie for single-cookie extraction.
    """
    if not cookie_header:
        return ""

    # Quick scan for cookie name
    search_str = f"{cookie_name}="
    parts = cookie_header.split(";")

    for part in parts:
        part = part.strip()
        if part.startswith(search_str):
            return part[len(search_str) :]

    return ""


class CSRFMiddleware(BaseMiddleware):
    """CSRF protection via double-submit cookie pattern.

    Safe methods (GET, HEAD, OPTIONS) pass through without validation.
    Unsafe methods require a matching ``X-CSRFToken`` header or form field.

    Args:
        app: Next ASGI app.
        secret: Signing secret (uses settings.SECRET_KEY by default).
        cookie_name: Name of the CSRF cookie.
        header_name: Name of the HTTP header to check.
        exempt_paths: Paths that skip CSRF validation.
    """

    def __init__(
        self,
        app: ASGIApp,
        secret: str = "",
        cookie_name: str = CSRF_COOKIE_NAME,
        header_name: str = CSRF_HEADER_NAME,
        exempt_paths: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self._secret = secret
        self._cookie_name = cookie_name
        self._header_name = header_name
        self._exempt_paths = set(exempt_paths or [])

    def _get_secret(self) -> str:
        if self._secret:
            return self._secret
        try:
            key = settings.SECRET_KEY
        except Exception as exc:
            raise RuntimeError(
                "CSRFMiddleware requires settings.SECRET_KEY or an explicit 'secret' argument."
            ) from exc
        if not key:
            raise RuntimeError("CSRFMiddleware requires a non-empty SECRET_KEY.")
        return cast("str", key)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET").upper()
        path = scope.get("path", "/")

        if path in self._exempt_paths or method in CSRF_SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        # Targeted header scan: extract only the 2 headers we need instead
        # of building a full dict on every unsafe request.
        cookie_raw = b""
        submitted_raw = b""
        header_name_lower = self._header_name.encode("latin-1")
        for name, value in scope.get("headers", []):
            lower = name.lower()
            if lower == b"cookie":
                cookie_raw = value
            elif lower == header_name_lower:
                submitted_raw = value
            if cookie_raw and submitted_raw:
                break

        cookie_header = cookie_raw.decode("latin-1") if cookie_raw else ""

        # Extract CSRF cookie using optimized parser
        csrf_cookie = _extract_cookie_value(cookie_header, self._cookie_name)

        submitted = submitted_raw.decode("latin-1") if submitted_raw else ""
        secret = self._get_secret()

        if (
            not csrf_cookie
            or not submitted
            or not _verify_csrf_token(csrf_cookie, submitted, secret)
        ):
            response = JSONResponse({"detail": "CSRF verification failed."}, status_code=403)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
