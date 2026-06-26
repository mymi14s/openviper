"""Shared HTTP type aliases and protocols."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from openviper.http.request import Request
    from openviper.http.views import View

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]
type ASGIMessage = dict[str, object]
type ASGIScope = dict[str, object]
type ASGIReceive = Callable[[], Awaitable[ASGIMessage]]
type ASGISend = Callable[[ASGIMessage], Awaitable[None]]
type TemplateContext = dict[str, object]


@runtime_checkable
class AuthenticatorProtocol(Protocol):
    """Structural type for authentication backends."""

    async def authenticate(self, request: Request) -> tuple[UserProtocol, object] | None: ...


@runtime_checkable
class PermissionProtocol(Protocol):
    """Structural type for permission classes."""

    async def has_permission(self, request: Request, view: View) -> bool: ...

    async def has_object_permission(self, request: Request, view: View, obj: object) -> bool: ...


@runtime_checkable
class ThrottleProtocol(Protocol):
    """Structural type for throttle classes."""

    async def allow_request(self, request: Request, view: View) -> bool: ...

    def wait(self) -> float | None: ...


@runtime_checkable
class UserProtocol(Protocol):
    """Structural type for user objects attached to requests."""

    is_authenticated: bool
    is_staff: bool
    is_superuser: bool

    async def has_role(self, role_name: str) -> bool: ...

    async def has_perm(self, codename: str) -> bool: ...


class MultipartField(Protocol):
    """Structural type for python-multipart field callbacks."""

    field_name: bytes
    value: bytes


class MultipartFile(Protocol):
    """Structural type for python-multipart file callbacks."""

    field_name: bytes
    file_name: bytes | None
    content_type: bytes | str | None
    file_object: object
