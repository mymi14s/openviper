"""Reusable test factories for the OpenViper test suite.

All factories live here to keep individual test modules import-free from
one another.  Import from this module in conftest.py or test files::

    from tests.factories import (
        make_scope,
        make_request,
        MockUser,
        MockQuerySet,
        ...
    )
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from typing import Any

from openviper.conf.settings import Settings
from openviper.http.request import Request

# ---------------------------------------------------------------------------
# ASGI helpers
# ---------------------------------------------------------------------------


def make_scope(
    *,
    path: str = "/",
    method: str = "GET",
    headers: list[tuple[bytes, bytes]] | None = None,
    query_string: bytes = b"",
    scope_type: str = "http",
    host: str = "testserver",
    **extra: Any,
) -> dict[str, Any]:
    """Build a minimal ASGI HTTP scope dict."""
    raw_headers: list[tuple[bytes, bytes]] = headers or []
    # Ensure host header is present
    header_names = {k.lower() for k, _ in raw_headers}
    if b"host" not in header_names:
        raw_headers = [(b"host", host.encode())] + list(raw_headers)
    return {
        "type": scope_type,
        "method": method.upper(),
        "path": path,
        "query_string": query_string,
        "headers": raw_headers,
        "server": (host, 80),
        "client": ("127.0.0.1", 9999),
        **extra,
    }


def make_websocket_scope(path: str = "/ws") -> dict[str, Any]:
    """Build a minimal ASGI WebSocket scope dict."""
    return {
        "type": "websocket",
        "path": path,
        "query_string": b"",
        "headers": [],
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 9999),
    }


def make_lifespan_scope() -> dict[str, Any]:
    """Build an ASGI lifespan scope dict."""
    return {"type": "lifespan"}


async def collect_send(scope: dict[str, Any], receive: Any, app: Any) -> list[dict[str, Any]]:
    """Run *app* and collect all ASGI send messages."""
    messages: list[dict[str, Any]] = []

    async def send(msg: dict[str, Any]) -> None:
        messages.append(msg)

    await app(scope, receive, send)
    return messages


async def noop_receive() -> dict[str, Any]:
    """An ASGI receive callable that returns a disconnect."""
    return {"type": "http.disconnect"}


async def body_receive(body: bytes = b"") -> dict[str, Any]:
    """Return a single http.request message with the given body."""
    return {"type": "http.request", "body": body, "more_body": False}


def make_receive(body: bytes = b"") -> Any:
    """Return a receive callable that yields one http.request message."""

    async def _receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    return _receive


# ---------------------------------------------------------------------------
# Mock user objects
# ---------------------------------------------------------------------------


class MockUser:
    """Minimal user object for middleware and auth tests."""

    def __init__(
        self,
        *,
        user_id: int = 1,
        username: str = "testuser",
        email: str = "test@example.com",
        is_authenticated: bool = True,
        is_superuser: bool = False,
        is_active: bool = True,
        roles: list[str] | None = None,
        permissions: list[str] | None = None,
    ) -> None:
        self.id = user_id
        self.username = username
        self.email = email
        self.is_authenticated = is_authenticated
        self.is_superuser = is_superuser
        self.is_active = is_active
        self._roles = roles or []
        self._permissions = permissions or []

    async def has_perm(self, codename: str) -> bool:
        return codename in self._permissions

    async def has_model_perm(self, model_label: str, action: str) -> bool:
        return self.is_superuser

    async def has_role(self, role: str) -> bool:
        return role in self._roles

    async def check_password(self, raw_password: str) -> bool:
        return True


class AnonymousMockUser:
    """Anonymous user object for middleware tests."""

    is_authenticated = False
    is_superuser = False
    id = None
    username = ""


# ---------------------------------------------------------------------------
# Mock QuerySet
# ---------------------------------------------------------------------------


class MockQuerySet:
    """A minimal async queryset mock for testing serializers / admin actions."""

    def __init__(self, items: list[Any] | None = None) -> None:
        self._items = list(items or [])

    async def count(self) -> int:
        return len(self._items)

    async def delete(self) -> None:
        self._items.clear()

    async def all(self) -> list[Any]:
        return list(self._items)

    async def first(self) -> Any | None:
        return self._items[0] if self._items else None

    def filter(self, **kwargs: Any) -> MockQuerySet:
        return self

    def exclude(self, **kwargs: Any) -> MockQuerySet:
        return self

    def offset(self, n: int) -> MockQuerySet:
        return MockQuerySet(self._items[n:])

    def limit(self, n: int) -> MockQuerySet:
        return MockQuerySet(self._items[:n])

    async def update(self, **kwargs: Any) -> int:
        return len(self._items)

    async def _aiter_items(self) -> AsyncIterator[Any]:
        for item in self._items:
            yield item

    async def batch(self, size: int = 25) -> AsyncIterator[list[Any]]:
        for i in range(0, len(self._items), size):
            yield self._items[i : i + size]


# ---------------------------------------------------------------------------
# Simple model-like objects
# ---------------------------------------------------------------------------


class SimpleModel:
    """Minimal object that can be used as an ORM model stub."""

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


def make_model(**kwargs: Any) -> SimpleModel:
    """Factory to create a SimpleModel with given attributes."""
    return SimpleModel(**kwargs)


# ---------------------------------------------------------------------------
# Request factory
# ---------------------------------------------------------------------------


def make_request(
    *,
    path: str = "/",
    method: str = "GET",
    headers: list[tuple[bytes, bytes]] | None = None,
    body: bytes = b"",
    query_string: bytes = b"",
    user: Any = None,
    path_params: dict[str, Any] | None = None,
) -> Any:
    """Create a minimal Request object for unit tests."""
    scope = make_scope(
        path=path,
        method=method,
        headers=headers,
        query_string=query_string,
    )
    receive = make_receive(body)
    req = Request(scope, receive)
    req.user = user
    req.path_params = path_params or {}
    return req


# ---------------------------------------------------------------------------
# Settings factory
# ---------------------------------------------------------------------------


def make_settings(**overrides: Any) -> Any:
    """Create a Settings instance with default + override values."""
    defaults: dict[str, Any] = {
        "SECRET_KEY": "test-secret",
        "DEBUG": True,
        "ALLOWED_HOSTS": ("*",),
        "DATABASE_URL": "sqlite+aiosqlite:///test.db",
    }
    defaults.update(overrides)
    # Only pass fields that actually exist on Settings
    valid_fields = {f.name for f in dataclasses.fields(Settings)}
    filtered = {k: v for k, v in defaults.items() if k in valid_fields}
    return Settings(**filtered)


# ---------------------------------------------------------------------------
# ASGI app helpers
# ---------------------------------------------------------------------------


def noop_app() -> Any:
    """Return an ASGI callable that does nothing (for lifespan / non-http)."""

    async def _app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        pass

    return _app


def echo_app(status: int = 200, body: bytes = b"OK") -> Any:
    """Return an ASGI callable that always responds with status + body."""

    async def _app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": body})

    return _app
