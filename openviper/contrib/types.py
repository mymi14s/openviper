"""Shared contrib type aliases."""

from collections.abc import Awaitable, Callable

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]
type ASGIMessage = dict[str, object]
type ASGIScope = dict[str, object]
type ASGIReceive = Callable[[], Awaitable[ASGIMessage]]
type ASGISend = Callable[[ASGIMessage], Awaitable[None]]
type ASGIApp = Callable[[ASGIScope, ASGIReceive, ASGISend], Awaitable[None]]
