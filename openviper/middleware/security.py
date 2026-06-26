"""Security middleware: HSTS, X-Content-Type-Options, X-Frame-Options, etc."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from openviper.conf import settings
from openviper.middleware.base import ASGIApp, BaseMiddleware

if TYPE_CHECKING:
    from openviper.http.types import ASGIMessage, ASGIReceive, ASGIScope, ASGISend, JsonValue

logger = logging.getLogger("openviper.middleware.security")


class SecurityMiddleware(BaseMiddleware):
    """Adds HTTP security headers to all responses.

    Headers added:

    - ``X-Content-Type-Options: nosniff``
    - ``X-Frame-Options: DENY`` (configurable)
    - ``Referrer-Policy: strict-origin-when-cross-origin``
    - ``Strict-Transport-Security`` (when ``hsts_seconds > 0``)
    - Redirect HTTP → HTTPS when ``ssl_redirect=True``

    Args:
        app: Next ASGI app.
        ssl_redirect: Redirect all HTTP requests to HTTPS.
        hsts_seconds: HSTS max-age. ``0`` disables the header.
        hsts_include_subdomains: Include subdomains in HSTS.
        hsts_preload: Add preload directive to HSTS.
        x_frame_options: ``DENY``, ``SAMEORIGIN``, or empty to disable.
        content_type_nosniff: Add ``X-Content-Type-Options: nosniff``.
        xss_filter: Add ``X-XSS-Protection: 1; mode=block``.
        csp: Optional Content-Security-Policy dictionary or string.
        permissions_policy: Value for the ``Permissions-Policy`` header.
        cross_origin_opener_policy: Value for the ``Cross-Origin-Opener-Policy`` header.
        cross_origin_embedder_policy: Value for the ``Cross-Origin-Embedder-Policy`` header.
        cross_origin_resource_policy: Value for the ``Cross-Origin-Resource-Policy`` header.
    """

    __slots__ = (
        "ssl_redirect",
        "hsts_seconds",
        "hsts_include_subdomains",
        "hsts_preload",
        "x_frame_options",
        "content_type_nosniff",
        "xss_filter",
        "csp",
        "permissions_policy",
        "cross_origin_opener_policy",
        "cross_origin_embedder_policy",
        "cross_origin_resource_policy",
        "_fixed_headers",
        "_exact_hosts",
        "_wildcard_hosts",
        "_allow_all_hosts",
    )

    def __init__(
        self,
        app: ASGIApp,
        ssl_redirect: bool | None = None,
        hsts_seconds: int | None = None,
        hsts_include_subdomains: bool | None = None,
        hsts_preload: bool | None = None,
        x_frame_options: str | None = None,
        content_type_nosniff: bool = True,
        xss_filter: bool | None = None,
        csp: dict[str, JsonValue] | str | None = None,
        permissions_policy: str | None = None,
        cross_origin_opener_policy: str | None = None,
        cross_origin_embedder_policy: str | None = None,
        cross_origin_resource_policy: str | None = None,
    ) -> None:
        super().__init__(app)
        self.ssl_redirect = (
            ssl_redirect
            if ssl_redirect is not None
            else getattr(settings, "SECURE_SSL_REDIRECT", False)
        )
        self.hsts_seconds = (
            hsts_seconds
            if hsts_seconds is not None
            else getattr(settings, "SECURE_HSTS_SECONDS", 0)
        )
        self.hsts_include_subdomains = (
            hsts_include_subdomains
            if hsts_include_subdomains is not None
            else getattr(settings, "SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
        )
        self.hsts_preload = (
            hsts_preload
            if hsts_preload is not None
            else getattr(settings, "SECURE_HSTS_PRELOAD", False)
        )
        self.x_frame_options = (
            x_frame_options
            if x_frame_options is not None
            else getattr(settings, "X_FRAME_OPTIONS", "DENY")
        )
        self.content_type_nosniff = content_type_nosniff
        self.xss_filter = (
            xss_filter
            if xss_filter is not None
            else getattr(settings, "SECURE_BROWSER_XSS_FILTER", False)
        )
        if self.xss_filter:
            logger.warning(
                "SECURE_BROWSER_XSS_FILTER is deprecated. "
                "The X-XSS-Protection header is removed from modern browsers "
                "and IE's implementation introduced XSS vectors. "
                "Use Content-Security-Policy instead."
            )
        self.csp = (
            csp if csp is not None else getattr(settings, "SECURE_CONTENT_SECURITY_POLICY", None)
        )
        self.permissions_policy = (
            permissions_policy
            if permissions_policy is not None
            else getattr(settings, "SECURE_PERMISSIONS_POLICY", None)
        )
        self.cross_origin_opener_policy = (
            cross_origin_opener_policy
            if cross_origin_opener_policy is not None
            else getattr(settings, "SECURE_CROSS_ORIGIN_OPENER_POLICY", None)
        )
        self.cross_origin_embedder_policy = (
            cross_origin_embedder_policy
            if cross_origin_embedder_policy is not None
            else getattr(settings, "SECURE_CROSS_ORIGIN_EMBEDDER_POLICY", None)
        )
        self.cross_origin_resource_policy = (
            cross_origin_resource_policy
            if cross_origin_resource_policy is not None
            else getattr(settings, "SECURE_CROSS_ORIGIN_RESOURCE_POLICY", None)
        )

        self._fixed_headers: list[tuple[bytes, bytes]] = []
        if content_type_nosniff:
            self._fixed_headers.append((b"x-content-type-options", b"nosniff"))
        if self.x_frame_options:
            self._fixed_headers.append((b"x-frame-options", self.x_frame_options.encode("latin-1")))
        self._fixed_headers.append((b"referrer-policy", b"strict-origin-when-cross-origin"))
        if self.hsts_seconds > 0:
            hsts = f"max-age={self.hsts_seconds}"
            if self.hsts_include_subdomains:
                hsts += "; includeSubDomains"
            if self.hsts_preload:
                hsts += "; preload"
            self._fixed_headers.append((b"strict-transport-security", hsts.encode("latin-1")))
        if self.xss_filter:
            self._fixed_headers.append((b"x-xss-protection", b"1; mode=block"))
        if self.permissions_policy is not None:
            self._fixed_headers.append(
                (b"permissions-policy", self.permissions_policy.encode("latin-1"))
            )
        if self.cross_origin_opener_policy is not None:
            self._fixed_headers.append(
                (
                    b"cross-origin-opener-policy",
                    self.cross_origin_opener_policy.encode("latin-1"),
                )
            )
        if self.cross_origin_embedder_policy is not None:
            self._fixed_headers.append(
                (
                    b"cross-origin-embedder-policy",
                    self.cross_origin_embedder_policy.encode("latin-1"),
                )
            )
        if self.cross_origin_resource_policy is not None:
            self._fixed_headers.append(
                (
                    b"cross-origin-resource-policy",
                    self.cross_origin_resource_policy.encode("latin-1"),
                )
            )
        if self.csp:
            if isinstance(self.csp, dict):
                sanitized_parts: list[str] = []
                for k, v in self.csp.items():
                    key = str(k).replace(";", "")
                    if isinstance(v, list):
                        val = " ".join(str(item).replace(";", "") for item in v)
                    else:
                        val = str(v).replace(";", "")
                    sanitized_parts.append(f"{key} {val}")
                csp_str = "; ".join(sanitized_parts)
            else:
                csp_str = str(self.csp)
            self._fixed_headers.append((b"content-security-policy", csp_str.encode("latin-1")))

        raw_hosts: list[str] | tuple[str, ...] = getattr(settings, "ALLOWED_HOSTS", ())
        self._allow_all_hosts: bool = "*" in raw_hosts
        self._exact_hosts: frozenset[str] = frozenset(
            h.lower() for h in raw_hosts if h != "*" and not h.startswith(".")
        )
        self._wildcard_hosts: tuple[str, ...] = tuple(
            h.lower() for h in raw_hosts if h.startswith(".")
        )

    def is_host_allowed(self, host: str) -> bool:
        """O(1) for exact matches; O(k) for wildcard suffixes."""
        if self._allow_all_hosts:
            return True
        host_lower = host.lower()
        if host_lower in self._exact_hosts:
            return True
        for pattern in self._wildcard_hosts:
            if host_lower.endswith(pattern) or host_lower == pattern[1:]:
                return True
        return False

    def get_host(self, scope: ASGIScope) -> str:
        """Extract the hostname (without port) from the ASGI scope."""
        headers = cast("list[tuple[bytes, bytes]]", scope.get("headers", []))
        for name, value in headers:
            if name == b"host":
                raw: str = value.decode("latin-1")
                return self.strip_port(raw)
        server = scope.get("server")
        if server:
            host, _port = cast("tuple[str, int]", server)
            return host
        return ""

    @staticmethod
    def strip_port(raw: str) -> str:
        """Remove port from host, handling IPv6 bracket notation."""
        if raw.startswith("["):
            bracket_end = raw.find("]")
            if bracket_end != -1:
                return raw[1:bracket_end]
            return raw[1:]
        if ":" in raw:
            return raw.rsplit(":", 1)[0]
        return raw

    async def send_400(self, send: ASGISend) -> None:
        """Send a 400 Bad Request response for disallowed hosts.

        The response body is intentionally generic to avoid reflecting
        attacker-controlled input.
        """
        body = b"Invalid Host header."
        await send(
            {
                "type": "http.response.start",
                "status": 400,
                "headers": [
                    [b"content-type", b"text/plain; charset=utf-8"],
                    [b"content-length", str(len(body)).encode("latin-1")],
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        host = ""
        raw_host = "localhost"
        headers = cast("list[tuple[bytes, bytes]]", scope.get("headers", []))
        for name, value in headers:
            if name == b"host":
                raw_host = value.decode("latin-1")
                host = self.strip_port(raw_host)
                break
        if not host:
            server = scope.get("server")
            if server:
                host, _port = cast("tuple[str, int]", server)
                raw_host = host

        # Header-control bytes would make redirects and errors ambiguous.
        if "\r" in raw_host or "\n" in raw_host or "\0" in raw_host:
            await self.send_400(send)
            return

        if not self.is_host_allowed(host):
            await self.send_400(send)
            return

        if self.ssl_redirect and scope.get("scheme") == "http":
            path = cast("str", scope.get("path", "/"))
            qs = cast("bytes", scope.get("query_string", b""))
            # CRLF injection allows attacker-controlled response splitting.
            if "\r" in path or "\n" in path:
                await self.send_400(send)
                return
            qs_str = qs.decode("latin-1") if qs else ""
            if "\r" in qs_str or "\n" in qs_str:
                await self.send_400(send)
                return
            url = f"https://{raw_host}{path}"
            if qs_str:
                url += f"?{qs_str}"
            await send(
                {
                    "type": "http.response.start",
                    "status": 301,
                    "headers": [
                        [b"location", url.encode("latin-1")],
                        [b"content-length", b"0"],
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return

        fixed = self._fixed_headers

        async def send_with_security(message: ASGIMessage) -> None:
            if message["type"] == "http.response.start":
                headers = cast("list[tuple[bytes, bytes]]", message.get("headers", []))
                headers = list(headers)
                headers.extend(fixed)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_security)
