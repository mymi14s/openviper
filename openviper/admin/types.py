"""Shared structural types for the admin package."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject = dict[str, JsonValue]

ASGIMessage = dict[str, object]
ASGIScope = dict[str, object]
ASGIReceive = Callable[[], Awaitable[ASGIMessage]]
ASGISend = Callable[[ASGIMessage], Awaitable[None]]
