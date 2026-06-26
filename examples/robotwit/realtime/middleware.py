"""ASGI middleware that routes WebSocket connections to the timeline consumer."""

from __future__ import annotations

from openviper.http.types import ASGIReceive, ASGIScope, ASGISend
from openviper.middleware.base import BaseMiddleware
from realtime.consumers import websocket_application


class WebSocketMiddleware(BaseMiddleware):
    """Intercept WebSocket connections and route them to the realtime consumer."""

    async def __call__(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        if scope["type"] == "websocket":
            await websocket_application(scope, receive, send)
            return
        await self.app(scope, receive, send)
