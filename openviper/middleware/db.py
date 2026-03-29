"""Database connection middleware for high-throughput applications.

Pins a single pooled connection for the lifetime of each HTTP/WebSocket
request.  All ORM calls within the request reuse the same connection,
eliminating per-query pool-checkout overhead.

This is the pattern used by Twitter/X, Google, and other services handling
millions of requests per second:

1. **Connection reuse** — One pool checkout per request instead of per query.
2. **Reduced pool contention** — Fewer concurrent checkouts under high QPS.
3. **Consistent reads** — All queries in a request see the same DB snapshot
   when combined with ``READ COMMITTED`` or stricter isolation.

Usage:
    Add to your middleware stack::

        MIDDLEWARE = [
            "openviper.middleware.db.DatabaseMiddleware",
            ...
        ]

    Or use directly::

        from openviper.middleware.db import DatabaseMiddleware
        app = DatabaseMiddleware(app)
"""

from __future__ import annotations

from typing import Any

from openviper.db.connection import request_connection
from openviper.middleware.base import BaseMiddleware


class DatabaseMiddleware(BaseMiddleware):
    """Pin a single pooled DB connection for each HTTP/WebSocket request.

    Stores the connection in a ``ContextVar`` so all ORM calls
    (``get_connection()``, ``_connect()``, ``_begin()``) automatically
    reuse it without any application code changes.

    For non-HTTP scopes (lifespan, etc.) the request is passed through
    without connection pinning.
    """

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        async with request_connection():
            await self.app(scope, receive, send)
