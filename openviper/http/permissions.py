"""Permission classes for OpenViper HTTP views.

Provides a pluggable permission system similar to Django Rest Framework.
"""

from __future__ import annotations

from abc import ABC, ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openviper.http.request import Request
    from openviper.http.views import View


class PermissionMetaclass(ABCMeta):
    def __and__(cls, other: Any) -> OperandHolder:
        return OperandHolder(AND, cls, other)

    def __or__(cls, other: Any) -> OperandHolder:  # type: ignore[override]
        return OperandHolder(OR, cls, other)

    def __rand__(cls, other: Any) -> OperandHolder:
        return OperandHolder(AND, other, cls)

    def __ror__(cls, other: Any) -> OperandHolder:  # type: ignore[override]
        return OperandHolder(OR, other, cls)

    def __invert__(cls) -> OperandHolder:
        return OperandHolder(NOT, cls)


class BasePermission(ABC, metaclass=PermissionMetaclass):
    """Abstract base class for all permission classes."""

    @abstractmethod
    async def has_permission(self, request: Request, view: View) -> bool:
        """Check if the request has permission to access the view.

        Return True to allow, False to deny.
        """
        return True

    async def has_object_permission(self, request: Request, view: View, obj: Any) -> bool:
        """Check if the request has permission to access a specific object.

        Return True to allow, False to deny.
        """
        return True

    def __and__(self, other: Any) -> OperandHolder:
        return OperandHolder(AND, self, other)

    def __or__(self, other: Any) -> OperandHolder:
        return OperandHolder(OR, self, other)

    def __rand__(self, other: Any) -> OperandHolder:
        return OperandHolder(AND, other, self)

    def __ror__(self, other: Any) -> OperandHolder:
        return OperandHolder(OR, other, self)

    def __invert__(self) -> OperandHolder:
        return OperandHolder(NOT, self)


class AND:
    def __init__(
        self, first: BasePermission | OperandHolder, second: BasePermission | OperandHolder
    ) -> None:
        self.first = first
        self.second = second

    async def has_permission(self, request: Request, view: View) -> bool:
        async def _check(perm: BasePermission | OperandHolder) -> bool:
            if isinstance(perm, OperandHolder):
                return await perm().has_permission(request, view)
            return await perm.has_permission(request, view)

        return await _check(self.first) and await _check(self.second)

    async def has_object_permission(self, request: Request, view: View, obj: Any) -> bool:
        async def _check(perm: BasePermission | OperandHolder) -> bool:
            if isinstance(perm, OperandHolder):
                return await perm().has_object_permission(request, view, obj)
            return await perm.has_object_permission(request, view, obj)

        return await _check(self.first) and await _check(self.second)


class OR:
    def __init__(
        self, first: BasePermission | OperandHolder, second: BasePermission | OperandHolder
    ) -> None:
        self.first = first
        self.second = second

    async def has_permission(self, request: Request, view: View) -> bool:
        async def _check(perm: BasePermission | OperandHolder) -> bool:
            if isinstance(perm, OperandHolder):
                return await perm().has_permission(request, view)
            return await perm.has_permission(request, view)

        return await _check(self.first) or await _check(self.second)

    async def has_object_permission(self, request: Request, view: View, obj: Any) -> bool:
        async def _check(perm: BasePermission | OperandHolder) -> bool:
            if isinstance(perm, OperandHolder):
                return await perm().has_object_permission(request, view, obj)
            return await perm.has_object_permission(request, view, obj)

        return await _check(self.first) or await _check(self.second)


class NOT:
    def __init__(self, first: BasePermission | OperandHolder) -> None:
        self.first = first

    async def has_permission(self, request: Request, view: View) -> bool:
        if isinstance(self.first, OperandHolder):
            return not await self.first().has_permission(request, view)
        return not await self.first.has_permission(request, view)

    async def has_object_permission(self, request: Request, view: View, obj: Any) -> bool:
        if isinstance(self.first, OperandHolder):
            return not await self.first().has_object_permission(request, view, obj)
        return not await self.first.has_object_permission(request, view, obj)


class OperandHolder:
    def __init__(
        self,
        operator_class: type[AND] | type[OR] | type[NOT],
        *args: Any,
    ) -> None:
        self.operator_class = operator_class
        # Ensure we instantiate classes if passed as types
        self.args = [arg() if isinstance(arg, type) else arg for arg in args]

    def __call__(self) -> BasePermission:
        return self.operator_class(*self.args)  # type: ignore[return-value]

    def __and__(self, other: Any) -> OperandHolder:
        return OperandHolder(AND, self, other)

    def __or__(self, other: Any) -> OperandHolder:
        return OperandHolder(OR, self, other)

    def __invert__(self) -> OperandHolder:
        return OperandHolder(NOT, self)


class AllowAny(BasePermission):
    """Always allow access."""

    async def has_permission(self, request: Request, view: View) -> bool:
        return True


class IsAuthenticated(BasePermission):
    """Allow only authenticated users."""

    async def has_permission(self, request: Request, view: View) -> bool:
        return bool(request.user and request.user.is_authenticated)


class IsAdmin(BasePermission):
    """Allow only staff users or superusers."""

    async def has_permission(self, request: Request, view: View) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_staff or request.user.is_superuser)
        )


class IsAuthenticatedOrReadOnly(BasePermission):
    """Allow authenticated users, but permit read-only access to anyone."""

    async def has_permission(self, request: Request, view: View) -> bool:
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return bool(request.user and request.user.is_authenticated)


class HasRole(BasePermission):
    """Allow only users with a specific role."""

    def __init__(self, role_name: str) -> None:
        self.role_name = role_name

    async def has_permission(self, request: Request, view: View) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        return await request.user.has_role(self.role_name)


class HasPermission(BasePermission):
    """Allow only users with a specific permission codename."""

    def __init__(self, codename: str) -> None:
        self.codename = codename

    async def has_permission(self, request: Request, view: View) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        return await request.user.has_perm(self.codename)
