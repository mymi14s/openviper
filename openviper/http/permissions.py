"""Permission classes for OpenViper HTTP views.

Provides a pluggable permission system for OpenViper HTTP views.
"""

from __future__ import annotations

from abc import ABC, ABCMeta, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openviper.http.request import Request
    from openviper.http.views import View


class PermissionMetaclass(ABCMeta):
    def __and__(cls, other: type) -> OperandHolder:
        return OperandHolder(AND, cls, other)

    def __or__(cls, other: type) -> OperandHolder:
        return OperandHolder(OR, cls, other)

    def __rand__(cls, other: type) -> OperandHolder:
        return OperandHolder(AND, other, cls)

    def __ror__(cls, other: type) -> OperandHolder:
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

    async def has_object_permission(self, request: Request, view: View, obj: object) -> bool:
        """Check if the request has permission to access a specific object.

        Return True to allow, False to deny.
        """
        return True

    def __and__(self, other: BasePermission | OperandHolder) -> OperandHolder:
        return OperandHolder(AND, self, other)

    def __or__(self, other: BasePermission | OperandHolder) -> OperandHolder:
        return OperandHolder(OR, self, other)

    def __rand__(self, other: BasePermission | OperandHolder) -> OperandHolder:
        return OperandHolder(AND, other, self)

    def __ror__(self, other: BasePermission | OperandHolder) -> OperandHolder:
        return OperandHolder(OR, other, self)

    def __invert__(self) -> OperandHolder:
        return OperandHolder(NOT, self)


async def resolve_permission(
    perm: BasePermission | OperandHolder, request: Request, view: View
) -> bool:
    """Resolve a permission check, unwrapping OperandHolder if needed."""
    if isinstance(perm, OperandHolder):
        return await perm().has_permission(request, view)
    return await perm.has_permission(request, view)


async def resolve_object_permission(
    perm: BasePermission | OperandHolder, request: Request, view: View, obj: object
) -> bool:
    """Resolve an object-level permission check, unwrapping OperandHolder if needed."""
    if isinstance(perm, OperandHolder):
        return await perm().has_object_permission(request, view, obj)
    return await perm.has_object_permission(request, view, obj)


class AND:
    def __init__(
        self, first: BasePermission | OperandHolder, second: BasePermission | OperandHolder
    ) -> None:
        self.first = first
        self.second = second

    async def has_permission(self, request: Request, view: View) -> bool:
        return await resolve_permission(self.first, request, view) and await resolve_permission(
            self.second, request, view
        )

    async def has_object_permission(self, request: Request, view: View, obj: object) -> bool:
        return await resolve_object_permission(
            self.first, request, view, obj
        ) and await resolve_object_permission(self.second, request, view, obj)


class OR:
    def __init__(
        self, first: BasePermission | OperandHolder, second: BasePermission | OperandHolder
    ) -> None:
        self.first = first
        self.second = second

    async def has_permission(self, request: Request, view: View) -> bool:
        return await resolve_permission(self.first, request, view) or await resolve_permission(
            self.second, request, view
        )

    async def has_object_permission(self, request: Request, view: View, obj: object) -> bool:
        return await resolve_object_permission(
            self.first, request, view, obj
        ) or await resolve_object_permission(self.second, request, view, obj)


class NOT:
    def __init__(self, first: BasePermission | OperandHolder) -> None:
        self.first = first

    async def has_permission(self, request: Request, view: View) -> bool:
        return not await resolve_permission(self.first, request, view)

    async def has_object_permission(self, request: Request, view: View, obj: object) -> bool:
        return not await resolve_object_permission(self.first, request, view, obj)


class OperandHolder:
    def __init__(
        self,
        operator_class: type[AND] | type[OR] | type[NOT],
        *args: BasePermission | type[BasePermission],
    ) -> None:
        self.operator_class = operator_class
        self.args = [arg() if isinstance(arg, type) else arg for arg in args]

    def __call__(self) -> AND | OR | NOT:
        return self.operator_class(*self.args)

    def __and__(self, other: BasePermission | OperandHolder) -> OperandHolder:
        return OperandHolder(AND, self, other)

    def __or__(self, other: BasePermission | OperandHolder) -> OperandHolder:
        return OperandHolder(OR, self, other)

    def __invert__(self) -> OperandHolder:
        return OperandHolder(NOT, self)


class AllowAny(BasePermission):
    """Always allow access."""

    async def has_permission(self, request: Request, view: View) -> bool:
        return True


def is_user_authenticated(request: Request) -> bool:
    """Return whether *request* has an authenticated user attached."""
    return bool(request.user and request.user.is_authenticated)


class IsAuthenticated(BasePermission):
    """Allow only authenticated users."""

    async def has_permission(self, request: Request, view: View) -> bool:
        return is_user_authenticated(request)


class IsAdmin(BasePermission):
    """Allow only staff users or superusers."""

    async def has_permission(self, request: Request, view: View) -> bool:
        return bool(
            is_user_authenticated(request) and (request.user.is_staff or request.user.is_superuser)
        )


class IsAuthenticatedOrReadOnly(BasePermission):
    """Allow authenticated users, but permit read-only access to anyone."""

    async def has_permission(self, request: Request, view: View) -> bool:
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return is_user_authenticated(request)


class HasRole(BasePermission):
    """Allow only users with a specific role."""

    def __init__(self, role_name: str) -> None:
        self.role_name = role_name

    async def has_permission(self, request: Request, view: View) -> bool:
        if not is_user_authenticated(request):
            return False
        return await request.user.has_role(self.role_name)


class HasPermission(BasePermission):
    """Allow only users with a specific permission codename."""

    def __init__(self, codename: str) -> None:
        self.codename = codename

    async def has_permission(self, request: Request, view: View) -> bool:
        if not is_user_authenticated(request):
            return False
        return await request.user.has_perm(self.codename)
