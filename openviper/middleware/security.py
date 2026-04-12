"""Security middleware: HSTS, X-Content-Type-Options, X-Frame-Options, etc."""

from __future__ import annotations

from typing import Any, cast

from openviper.conf import settings
from openviper.middleware.base import ASGIApp, BaseMiddleware


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
        csp: dict[str, Any] | str | None = None,
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
            else getattr(settings, "SECURE_BROWSER_XSS_FILTER", True)
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

        # Pre-build fixed security headers — done once at init, zero per-request alloc.
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

        # Build O(1) ALLOWED_HOSTS lookup structures at init time.
        # Separate wildcard suffixes (`.example.com`) from exact matches.
        raw_hosts: list[str] | tuple[str, ...] = getattr(settings, "ALLOWED_HOSTS", ())
        self._allow_all_hosts: bool = "*" in raw_hosts
        self._exact_hosts: frozenset[str] = frozenset(
            h.lower() for h in raw_hosts if h != "*" and not h.startswith(".")
        )
        self._wildcard_hosts: tuple[str, ...] = tuple(
            h.lower() for h in raw_hosts if h.startswith(".")
        )

    def _is_host_allowed(self, host: str) -> bool:
        """O(1) for exact matches; O(k) for wildcard suffixes (k ≈ 0 in practice)."""
        if self._allow_all_hosts:
            return True
        host_lower = host.lower()
        if host_lower in self._exact_hosts:
            return True
        for pattern in self._wildcard_hosts:
            if host_lower.endswith(pattern) or host_lower == pattern[1:]:
                return True
        return False

    def _get_host(self, scope: dict[str, Any]) -> str:
        """Extract the hostname (without port) from the ASGI scope."""
        for name, value in scope.get("headers", []):
            if name == b"host":
                raw: str = value.decode("latin-1")
                return self._strip_port(raw)
        server = scope.get("server")
        if server:
            return cast("str", server[0])
        return ""

    @staticmethod
    def _strip_port(raw: str) -> str:
        """Remove port from host, handling IPv6 bracket notation."""
        if raw.startswith("["):
            # IPv6 bracket notation: [::1]:8000 or [::1]
            bracket_end = raw.find("]")
            if bracket_end != -1:
                return raw[1:bracket_end]
            return raw[1:]
        if ":" in raw:
            return raw.rsplit(":", 1)[0]
        return raw

    async def _send_400(self, send: Any, host: str) -> None:
        """Send a 400 Bad Request response for disallowed hosts."""
        body = f"Invalid HTTP_HOST header: '{host}'. The host is not allowed.".encode()
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

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Single header scan — extract both host and raw_host in one pass.
        host = ""
        raw_host = "localhost"
        for name, value in scope.get("headers", []):
            if name == b"host":
                raw_host = value.decode("latin-1")
                host = self._strip_port(raw_host)
                break
        if not host:
            server = scope.get("server")
            if server:
                host = raw_host = server[0]

        # ── ALLOWED_HOSTS check ──────────────────────────────────────────
        if not self._is_host_allowed(host):
            await self._send_400(send, host)
            return

        # ── SSL redirect ─────────────────────────────────────────────────
        if self.ssl_redirect and scope.get("scheme") == "http":
            path = scope.get("path", "/")
            qs = scope.get("query_string", b"")
            # Reject hosts containing CR/LF to prevent header injection
            # in the Location redirect value.
            if "\r" in raw_host or "\n" in raw_host:
                await self._send_400(send, host)
                return
            url = f"https://{raw_host}{path}"
            if qs:
                url += f"?{qs.decode('latin-1')}"
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

        async def send_with_security(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(fixed)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_security)
