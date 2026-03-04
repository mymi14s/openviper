"""Authentication and permission decorators."""

from __future__ import annotations

from functools import wraps
from typing import Callable

from openviper.http import JSONResponse, Request, Response


def login_required(func: Callable) -> Callable:
    """Decorator to require authentication."""

    @wraps(func)
    async def wrapper(self_or_request, *args, **kwargs):
        # Handle both function-based and class-based views
        if isinstance(self_or_request, Request):
            request = self_or_request
        else:
            request = args[0] if args else kwargs.get("request")

        if not hasattr(request, "user") or not request.user or not request.user.is_authenticated:
            return JSONResponse({"error": "Authentication required"}, status_code=401)

        return await func(self_or_request, *args, **kwargs)

    return wrapper


def role_required(role_name: str) -> Callable:
    """Decorator to require specific role."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self_or_request, *args, **kwargs):
            # Handle both function-based and class-based views
            if isinstance(self_or_request, Request):
                request = self_or_request
            else:
                request = args[0] if args else kwargs.get("request")

            if (
                not hasattr(request, "user")
                or not request.user
                or not request.user.is_authenticated
            ):
                return JSONResponse({"error": "Authentication required"}, status_code=401)

            has_role = await request.user.has_role(role_name)
            if not has_role and not request.user.is_superuser:
                return JSONResponse({"error": f"Role '{role_name}' required"}, status_code=403)

            return await func(self_or_request, *args, **kwargs)

        return wrapper

    return decorator


def permission_required(permission: str) -> Callable:
    """Decorator to require specific permission."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self_or_request, *args, **kwargs):
            # Handle both function-based and class-based views
            if isinstance(self_or_request, Request):
                request = self_or_request
            else:
                request = args[0] if args else kwargs.get("request")

            if (
                not hasattr(request, "user")
                or not request.user
                or not request.user.is_authenticated
            ):
                return JSONResponse({"error": "Authentication required"}, status_code=401)

            has_perm = await request.user.has_perm(permission)
            if not has_perm:
                return JSONResponse(
                    {"error": f"Permission '{permission}' required"}, status_code=403
                )

            return await func(self_or_request, *args, **kwargs)

        return wrapper

    return decorator
