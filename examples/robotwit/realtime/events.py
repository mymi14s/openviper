"""In-process event bus for WebSocket broadcasting."""

from __future__ import annotations

import asyncio
import logging
import typing as t

logger = logging.getLogger("openviper.realtime")



class EventBus:
    """Async event bus for broadcasting events to WebSocket consumers."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[dict[str, t.Any]]] = []

    def subscribe(self) -> asyncio.Queue[dict[str, t.Any]]:
        """Subscribe to events and return a queue to receive them."""
        queue: asyncio.Queue[dict[str, t.Any]] = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, t.Any]]) -> None:
        """Remove a subscriber queue."""
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    async def broadcast(self, event_type: str, payload: dict[str, t.Any]) -> None:
        """Broadcast an event to all subscribers."""
        event = {"type": event_type, "data": payload}
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Event queue full, dropping event for subscriber")


event_bus = EventBus()
