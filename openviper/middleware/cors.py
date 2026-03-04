"""CORS (Cross-Origin Resource Sharing) middleware."""

from __future__ import annotations

import fnmatch
import re
from typing import Any

from openviper.middleware.base import ASGIApp, BaseMiddleware


class CORSMiddleware(BaseMiddleware):
    """Handle Cross-Origin Resource Sharing headers.

    Origin patterns are compiled to :class:`re.Pattern` objects at
    ``__init__`` time so no per-request pattern compilation occurs.

    Args:
        app: Next ASGI app.
        allowed_origins: List of allowed origin strings. Supports wildcards.
        allow_credentials: Allow ``Authorization`` / cookies cross-origin.
        allowed_methods: Permitted HTTP methods.
        allowed_headers: Permitted request headers (``["*"]`` = all).
        expose_headers: Headers to expose to the browser.
        max_age: Preflight cache TTL in seconds.
    """

    __slots__ = (
        "allow_credentials",
        "max_age",
        "_allow_all_origins",
        "_allow_all_headers",
        "_exact_origins",
        "_wildcard_patterns",
        "_preflight_headers_base",
        "_expose_headers_entry",
        "_credentials_entry",
    )

    def __init__(
        self,
        app: ASGIApp,
        allowed_origins: list[str] | None = None,
        allow_credentials: bool = True,
        allowed_methods: list[str] | None = None,
        allowed_headers: list[str] | None = None,
        expose_headers: list[str] | None = None,
        max_age: int = 600,
    ) -> None:
        super().__init__(app)
        self.allow_credentials = allow_credentials
        self.max_age = max_age

        _origins = allowed_origins or ["*"]
        _methods = [m.upper() for m in (allowed_methods or ["*"])]
        _headers = [h.lower() for h in (allowed_headers or ["*"])]
        _expose = expose_headers or []

        self._allow_all_origins: bool = "*" in _origins
        self._allow_all_headers: bool = "*" in _headers

        # Partition allowed_origins into exact strings (fast frozenset lookup)
        # and wildcard patterns (compiled regex, typically 0 in production).
        self._exact_origins: frozenset[str] = frozenset(
            o for o in _origins if "*" not in o and "?" not in o
        )
        self._wildcard_patterns: tuple[re.Pattern[str], ...] = tuple(
            re.compile(fnmatch.translate(p)) for p in _origins if "*" in p or "?" in p
        )

        # Pre-build the static portions of preflight headers (everything
        # except access-control-allow-origin, which is request-dependent).
        preflight: list[tuple[bytes, bytes]] = []

        if allow_credentials:
            preflight.append((b"access-control-allow-credentials", b"true"))

        methods_str = ", ".join(
            _methods
            if "*" not in _methods
            else ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
        )
        preflight.append((b"access-control-allow-methods", methods_str.encode("latin-1")))

        if self._allow_all_headers:
            preflight.append((b"access-control-allow-headers", b"*"))
        else:
            preflight.append(
                (b"access-control-allow-headers", ", ".join(_headers).encode("latin-1"))
            )

        preflight.append((b"access-control-max-age", str(max_age).encode("latin-1")))

        self._preflight_headers_base: tuple[tuple[bytes, bytes], ...] = tuple(preflight)

        # Pre-encode the expose-headers entry (None when not needed).
        self._expose_headers_entry: tuple[bytes, bytes] | None = (
            (b"access-control-expose-headers", ", ".join(_expose).encode("latin-1"))
            if _expose
            else None
        )
        # Pre-encode the credentials entry for non-preflight responses.
        self._credentials_entry: tuple[bytes, bytes] | None = (
            (b"access-control-allow-credentials", b"true") if allow_credentials else None
        )

    def _origin_allowed(self, origin: str) -> bool:
        """O(1) for exact matches; regex scan for wildcard patterns (typically 0)."""
        if self._allow_all_origins:
            return True
        if origin in self._exact_origins:
            return True
        return any(p.match(origin) for p in self._wildcard_patterns)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract Origin header in a single pass.
        origin = ""
        for name, value in scope.get("headers", []):
            if name == b"origin":
                origin = value.decode("latin-1")
                break

        if not origin:
            await self.app(scope, receive, send)
            return

        is_preflight = scope.get("method", "GET").upper() == "OPTIONS"

        if is_preflight:
            cors_headers: list[Any] = []
            if self._origin_allowed(origin):
                cors_headers.append((b"access-control-allow-origin", origin.encode("latin-1")))
                cors_headers.extend(self._preflight_headers_base)
                if self._expose_headers_entry is not None:
                    cors_headers.append(self._expose_headers_entry)
            cors_headers.append((b"content-length", b"0"))
            await send(
                {
                    "type": "http.response.start",
                    "status": 204,
                    "headers": cors_headers,
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return

        # Build non-preflight CORS headers.
        extra: list[tuple[bytes, bytes]] = []
        if self._origin_allowed(origin):
            extra.append((b"access-control-allow-origin", origin.encode("latin-1")))
            if self._credentials_entry is not None:
                extra.append(self._credentials_entry)
            if self._expose_headers_entry is not None:
                extra.append(self._expose_headers_entry)

        if not extra:
            await self.app(scope, receive, send)
            return

        async def send_with_cors(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", [])) + extra
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cors)
