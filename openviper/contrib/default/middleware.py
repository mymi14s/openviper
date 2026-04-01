"""Middleware that serves a beautiful default landing page in DEBUG mode.

When ``settings.DEBUG`` is ``True`` and the application has no user-defined
routes (only the built-in OpenAPI routes), a GET request to ``/`` returns
the OpenViper welcome page.  In production (DEBUG=False), returns a standard 404.
"""

from __future__ import annotations

from html import escape
from typing import Any

from openviper import __version__
from openviper.contrib.default.landing import LANDING_HTML
from openviper.http.response import HTMLResponse

_404_RESPONSE = HTMLResponse("<h1>404 Not Found</h1>", status_code=404)


class DefaultLandingMiddleware:
    """ASGI middleware: serve a welcome page when no custom root route exists.

    This middleware is automatically registered by ``OpenViper``.  It intercepts
    ``GET /`` only when the router has no user-defined route for that path.
    In debug mode, it shows a beautiful HTML landing page.  In production
    (DEBUG=False), it returns a standard 404 response.

    Args:
        app: The next ASGI application in the chain.
        debug: Whether the application is running in debug mode.
        version: OpenViper version string shown on the page.
        has_custom_root: Whether the router has a user-defined ``GET /`` route.
    """

    def __init__(
        self,
        app: Any,
        *,
        debug: bool = False,
        version: str = __version__,
        has_custom_root: bool = False,
    ) -> None:
        self.app = app
        self.debug = debug
        self.has_custom_root = has_custom_root
        # Pre-render and cache the landing page — version is immutable after init.
        # Escape the version string to prevent XSS via malformed config values.
        self._landing_response: HTMLResponse | None = None
        if debug and not has_custom_root:
            html = LANDING_HTML.replace("{version}", escape(version))
            self._landing_response = HTMLResponse(html)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if (
            not self.has_custom_root
            and scope.get("type") == "http"
            and scope.get("method", "GET").upper() == "GET"
            and scope.get("path", "/") == "/"
        ):
            if self._landing_response is not None:
                await self._landing_response(scope, receive, send)
            else:
                await _404_RESPONSE(scope, receive, send)
            return

        await self.app(scope, receive, send)
