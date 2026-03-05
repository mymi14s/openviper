"""CSRF protection middleware."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any, cast

from openviper.conf import settings
from openviper.http.response import JSONResponse
from openviper.middleware.base import ASGIApp, BaseMiddleware

CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
CSRF_COOKIE_NAME = "csrftoken"
CSRF_HEADER_NAME = "x-csrftoken"
CSRF_FORM_FIELD = "csrfmiddlewaretoken"


def _generate_csrf_token() -> str:
    return secrets.token_hex(32)


def _mask_csrf_token(token: str, secret: str) -> str:
    """Create a per-request masked token for the HTML form."""
    salt = secrets.token_hex(8)
    signature = hmac.new(secret.encode(), f"{salt}{token}".encode(), hashlib.sha256).hexdigest()
    return f"{salt}{signature}"


def _verify_csrf_token(cookie_token: str, submitted_token: str, secret: str) -> bool:
    """Constant-time verify that the submitted token matches the cookie."""
    if len(submitted_token) < 80:
        return False
    salt = submitted_token[:16]
    expected = hmac.new(
        secret.encode(), f"{salt}{cookie_token}".encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(submitted_token[16:], expected)


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
            return cast("str", settings.SECRET_KEY)
        except Exception:
            return "fallback-secret"

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET").upper()
        path = scope.get("path", "/")

        if path in self._exempt_paths or method in CSRF_SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        cookie_header = headers.get(b"cookie", b"").decode("latin-1")

        # Extract existing CSRF cookie
        csrf_cookie = ""
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith(f"{self._cookie_name}="):
                csrf_cookie = part[len(self._cookie_name) + 1 :]
                break

        submitted = headers.get(self._header_name.encode("latin-1"), b"").decode("latin-1")
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
