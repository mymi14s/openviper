"""Database connection middleware.

Pins a single pooled connection per HTTP/WebSocket request so all ORM
calls reuse the same checkout, reducing pool contention and ensuring
consistent reads under ``READ COMMITTED`` or stricter isolation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from openviper.db.connection import request_connection
from openviper.middleware.base import BaseMiddleware

if TYPE_CHECKING:
    from openviper.http.types import ASGIReceive, ASGIScope, ASGISend


class DatabaseMiddleware(BaseMiddleware):
    """Pin a single pooled DB connection for each HTTP/WebSocket request.

    Stores the connection in a ``ContextVar`` so all ORM calls
    (``get_connection()``, ``_connect()``, ``_begin()``) automatically
    reuse it without any application code changes.

    For non-HTTP scopes (lifespan, etc.) the request is passed through
    without connection pinning.
    """

    async def __call__(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        async with request_connection():
            await self.app(scope, receive, send)
