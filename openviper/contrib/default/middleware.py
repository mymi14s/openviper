"""Middleware that serves a beautiful default landing page in DEBUG mode.

When ``settings.DEBUG`` is ``True`` and the application has no user-defined
routes (only the built-in OpenAPI routes), a GET request to ``/`` returns
the OpenViper welcome page.  In production (DEBUG=False), returns a standard 404.
"""

from __future__ import annotations

from typing import Any

from openviper.contrib.default.landing import LANDING_HTML
from openviper.http.response import HTMLResponse


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
        version: str = "0.0.1",
        has_custom_root: bool = False,
    ) -> None:
        self.app = app
        self.debug = debug
        self.version = version
        self.has_custom_root = has_custom_root

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if (
            not self.has_custom_root
            and scope.get("type") == "http"
            and scope.get("method", "GET").upper() == "GET"
            and scope.get("path", "/") == "/"
        ):
            if self.debug:
                # Show beautiful HTML landing page in debug mode
                html = LANDING_HTML.replace("{version}", self.version)
                response = HTMLResponse(html)
            else:
                # Production: return 404 — the root path is not served by Openviper.
                # Static assets and the frontend should be handled by nginx or a CDN.
                response = HTMLResponse("<h1>404 Not Found</h1>", status_code=404)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
