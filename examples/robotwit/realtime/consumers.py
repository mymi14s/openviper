"""WebSocket consumer for real-time timeline updates."""

from __future__ import annotations

import asyncio
import json
import logging
import typing as t

from realtime.events import event_bus

logger = logging.getLogger("openviper.realtime")

if t.TYPE_CHECKING:
    import collections.abc as c


class TimelineConsumer:
    """WebSocket consumer that streams real-time events to clients."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[dict[str, t.Any]] | None = None

    async def on_connect(self, scope: dict[str, t.Any]) -> None:
        """Called when a WebSocket connection is established."""
        self._queue = event_bus.subscribe()
        logger.info("WebSocket client connected")

    async def on_disconnect(self, scope: dict[str, t.Any]) -> None:
        """Called when a WebSocket connection is closed."""
        if self._queue:
            event_bus.unsubscribe(self._queue)
            self._queue = None
        logger.info("WebSocket client disconnected")

    async def receive_events(self) -> c.AsyncIterator[str]:
        """Yield events as JSON strings for sending to the client."""
        if not self._queue:
            return
        while True:
            event = await self._queue.get()
            yield json.dumps(event)


async def websocket_application(
    scope: dict[str, t.Any],
    receive: c.Callable[[], t.Awaitable[dict[str, t.Any]]],
    send: c.Callable[[dict[str, t.Any]], t.Awaitable[None]],
) -> None:
    """ASGI WebSocket application for the timeline consumer."""
    consumer = TimelineConsumer()

    await send({"type": "websocket.accept"})
    await consumer.on_connect(scope)

    try:
        async for event_str in consumer.receive_events():
            await send({"type": "websocket.send", "text": event_str})
    except asyncio.CancelledError:
        pass
    finally:
        await consumer.on_disconnect(scope)
        await send({"type": "websocket.close"})
