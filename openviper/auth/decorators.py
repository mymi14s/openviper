"""Auth decorators for view-level access control.

Example:
    .. code-block:: python

        from openviper.auth.decorators import login_required, permission_required, role_required

        @app.get("/dashboard")
        @login_required
        async def dashboard(request):
            return {"user": request.user.username}

        @app.delete("/admin/users/{id}")
        @permission_required("user.delete")
        async def delete_user(request, id: int):
            ...

        @app.get("/reports")
        @role_required("manager")
        async def reports(request):
            ...
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any

from openviper.exceptions import PermissionDenied, Unauthorized
from openviper.http.request import Request


def login_required(func: Callable[..., Any]) -> Callable[..., Any]:
    """Require the request user to be authenticated.

    Raises:
        Unauthorized (401): User is not authenticated.
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        request = _get_request(args, kwargs)
        if request is None or not getattr(request.user, "is_authenticated", False):
            raise Unauthorized()
        result = func(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result

    return wrapper


def permission_required(codename: str) -> Callable[..., Any]:
    """Require the request user to have a specific permission.

    Args:
        codename: Permission codename, e.g. ``"post.create"``.

    Raises:
        Unauthorized (401): User is not authenticated.
        PermissionDenied (403): User lacks the required permission.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = _get_request(args, kwargs)
            if request is None or not getattr(request.user, "is_authenticated", False):
                raise Unauthorized()
            has_perm = await request.user.has_perm(codename)
            if not has_perm:
                raise PermissionDenied(f"Permission '{codename}' required.")
            result = func(*args, **kwargs)
            return await result if inspect.isawaitable(result) else result

        return wrapper

    return decorator


def role_required(role_name: str) -> Callable[..., Any]:
    """Require the request user to have a specific role.

    Args:
        role_name: Role name, e.g. ``"admin"``.

    Raises:
        Unauthorized (401): User is not authenticated.
        PermissionDenied (403): User lacks the required role.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = _get_request(args, kwargs)
            if request is None or not getattr(request.user, "is_authenticated", False):
                raise Unauthorized()
            has_role = await request.user.has_role(role_name)
            if not has_role:
                raise PermissionDenied(f"Role '{role_name}' required.")
            result = func(*args, **kwargs)
            return await result if inspect.isawaitable(result) else result

        return wrapper

    return decorator


def superuser_required(func: Callable[..., Any]) -> Callable[..., Any]:
    """Require request.user.is_superuser to be True.

    Raises:
        Unauthorized (401): User is not authenticated.
        PermissionDenied (403): User is not a superuser.
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        request = _get_request(args, kwargs)
        if request is None or not getattr(request.user, "is_authenticated", False):
            raise Unauthorized()
        if not getattr(request.user, "is_superuser", False):
            raise PermissionDenied("Superuser access required.")
        result = func(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result

    return wrapper


def staff_required(func: Callable[..., Any]) -> Callable[..., Any]:
    """Require request.user.is_staff to be True."""

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        request = _get_request(args, kwargs)
        if request is None or not getattr(request.user, "is_authenticated", False):
            raise Unauthorized()
        if not getattr(request.user, "is_staff", False):
            raise PermissionDenied("Staff access required.")
        result = func(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result

    return wrapper


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_request(args: tuple[Any, ...], kwargs: dict[str, Any] | None = None) -> Any | None:
    """Extract a Request from positional arguments or keyword arguments."""

    for arg in args:
        if isinstance(arg, Request):
            return arg
    if kwargs:
        for v in kwargs.values():
            if isinstance(v, Request):
                return v
    return None
