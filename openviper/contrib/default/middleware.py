"""Middleware serving a default landing page in DEBUG mode.

When settings.DEBUG is True and no user-defined root route exists,
GET / returns the OpenViper welcome page. In production, returns 404.
"""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING, cast

from openviper import __version__
from openviper.contrib.default.landing import LANDING_HTML
from openviper.http.response import HTMLResponse

if TYPE_CHECKING:
    from openviper.contrib.types import ASGIApp, ASGIReceive, ASGIScope, ASGISend

NOT_FOUND_RESPONSE = HTMLResponse("<h1>404 Not Found</h1>", status_code=404)


class DefaultLandingMiddleware:
    """ASGI middleware: serve welcome page when no custom root route exists."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        debug: bool = False,
        version: str = __version__,
        has_custom_root: bool = False,
    ) -> None:
        self.app = app
        self.debug = debug
        self.has_custom_root = has_custom_root
        self.landing_response: HTMLResponse | None = None
        if debug and not has_custom_root:
            html = LANDING_HTML.replace("{version}", escape(version))
            self.landing_response = HTMLResponse(html)

    async def __call__(
        self,
        scope: ASGIScope,
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        if (
            not self.has_custom_root
            and scope.get("type") == "http"
            and cast("str", scope.get("method", "GET")).upper() == "GET"
            and scope.get("path", "/") == "/"
        ):
            if self.landing_response is not None:
                await self.landing_response(scope, receive, send)
            else:
                await NOT_FOUND_RESPONSE(scope, receive, send)
            return

        await self.app(scope, receive, send)
