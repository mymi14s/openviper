"""Server error middleware for OpenViper.

:class:`ServerErrorMiddleware` is the outermost layer of the ASGI stack.
It catches *any* unhandled exception that escapes inner middleware or the
route handler and converts it into an HTTP 500 response.

In ``DEBUG`` mode the response is a rich HTML traceback page (see
:mod:`openviper.debug.traceback_page`).  In production a plain
``500 Internal Server Error`` text body is returned and the exception is
logged via the standard ``openviper.app`` logger.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from openviper.debug.traceback_page import render_debug_page
from openviper.http.request import Request

if TYPE_CHECKING:
    from openviper.debug.traceback_page import _DebugRequest
    from openviper.http.types import ASGIMessage, ASGIReceive, ASGIScope, ASGISend
    from openviper.middleware.base import ASGIApp

logger = logging.getLogger("openviper.app")

PLAIN_500_BODY = b"Internal Server Error"
PLAIN_500_HEADERS = [
    (b"content-type", b"text/plain; charset=utf-8"),
    (b"content-length", str(len(PLAIN_500_BODY)).encode()),
]


class ServerErrorMiddleware:
    """Outermost ASGI middleware that catches all unhandled exceptions.

    Every unhandled exception that would otherwise propagate to the ASGI
    server (and produce an empty or garbled client response) is caught here.

    * **DEBUG=True** - returns a rich HTML traceback page so developers see
      exactly what broke and where.
    * **DEBUG=False** - logs the exception at ERROR level and returns a plain
      ``500 Internal Server Error`` response that exposes no internals.

    If the response has already started being sent when the exception occurs
    (i.e. ``http.response.start`` was already sent downstream), the error can
    only be logged; no replacement response can be sent.

    Args:
        app: The next ASGI application in the chain.
        debug: Enable rich HTML debug output.  Defaults to ``False``.
    """

    __slots__ = ("app", "debug")

    def __init__(self, app: ASGIApp, *, debug: bool = False) -> None:
        self.app = app
        self.debug = debug

    async def __call__(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_wrapper(message: ASGIMessage) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            if response_started:
                logger.exception(
                    "Unhandled exception after response started (cannot send error page): %s",
                    exc,
                )
                raise

            logger.exception("Unhandled server error: %s", exc)

            if self.debug:
                await self.send_debug_page(scope, receive, send, exc)
            else:
                await self.send_plain_500(send)

    async def send_debug_page(
        self,
        scope: ASGIScope,
        receive: ASGIReceive,
        send: ASGISend,
        exc: Exception,
    ) -> None:
        """Render and send the HTML debug traceback page."""
        request = Request(scope, receive)
        body = render_debug_page(exc, cast("_DebugRequest", request)).encode("utf-8")
        headers = [
            (b"content-type", b"text/html; charset=utf-8"),
            (b"content-length", str(len(body)).encode()),
            (b"content-security-policy", b"default-src 'none'; style-src 'unsafe-inline'"),
            (b"x-content-type-options", b"nosniff"),
        ]
        await send({"type": "http.response.start", "status": 500, "headers": headers})
        await send({"type": "http.response.body", "body": body, "more_body": False})

    async def send_plain_500(self, send: ASGISend) -> None:
        """Send a plain-text 500 response without leaking any internals."""
        await send(
            {
                "type": "http.response.start",
                "status": 500,
                "headers": PLAIN_500_HEADERS,
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": PLAIN_500_BODY,
                "more_body": False,
            }
        )
