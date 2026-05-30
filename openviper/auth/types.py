"""Shared structural types for the authentication package."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

AuthValue = object
AuthPayload = dict[str, AuthValue]
ASGIMessage = dict[str, AuthValue]
ASGIScope = dict[str, AuthValue]
ASGIReceive = Callable[[], Awaitable[ASGIMessage]]
ASGISend = Callable[[ASGIMessage], Awaitable[None]]
ASGIApp = Callable[[ASGIScope, ASGIReceive, ASGISend], Awaitable[None]]


@runtime_checkable
class Authenticable(Protocol):
    """Structural type for user-like authentication objects."""

    @property
    def pk(self) -> int | str | None: ...

    @property
    def is_authenticated(self) -> object: ...

    @property
    def is_active(self) -> object: ...

    async def has_perm(self, codename: str) -> bool: ...
    async def has_role(self, role_name: str) -> bool: ...
    async def get_permissions(self) -> set[str]: ...


@dataclass(frozen=True)
class LoginCredentials:
    """Validated login payload."""

    username: str
    password: str

    @classmethod
    def from_request_body(cls, body: Mapping[str, object]) -> LoginCredentials:
        """Construct from a parsed JSON body."""
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        if not username or not password:
            raise ValueError("Username and password are required.")
        return cls(username=username, password=password)
