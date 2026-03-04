"""Admin authentication and permission middleware.

Provides middleware to protect admin routes and ensure only
authorized staff users can access the admin panel.
"""

from __future__ import annotations

from typing import Any

from openviper.http.response import JSONResponse
from openviper.middleware.base import BaseMiddleware


class AdminMiddleware(BaseMiddleware):
    """Middleware to protect admin routes.

    Ensures that only authenticated staff users can access
    routes under /admin/api/.
    """

    ADMIN_PATH_PREFIX = "/admin/api/"
    EXEMPT_PATHS = [
        "/admin/api/auth/login/",
        "/admin/api/auth/refresh/",
        "/admin/api/config/",
    ]

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        """Process the request.

        Args:
            scope: ASGI scope dict.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        # Normalize path for comparison (strip trailing slash)
        normalized_path = path.rstrip("/") + "/"

        # Skip non-admin paths
        if not normalized_path.startswith(self.ADMIN_PATH_PREFIX):
            await self.app(scope, receive, send)
            return

        # Skip exempt paths (login, refresh)
        if normalized_path in self.EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        # Check authentication
        if not await self.check_admin_authentication(scope):
            await self._send_unauthorized(scope, receive, send)
            return

        await self.app(scope, receive, send)

    async def check_admin_authentication(self, scope: dict[str, Any]) -> bool:
        """Check if the request is authenticated for admin access.

        Args:
            scope: ASGI scope dict.

        Returns:
            True if user is authenticated and is staff/superuser.
        """
        # User should be set by AuthenticationMiddleware
        user = scope.get("user")
        if user is None:
            return False

        # Check if user is authenticated
        if not getattr(user, "is_authenticated", False):
            return False

        # Check if user is staff or superuser
        is_staff = getattr(user, "is_staff", False)
        is_superuser = getattr(user, "is_superuser", False)

        return is_staff or is_superuser

    async def _send_unauthorized(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        """Send a 401 Unauthorized response.

        Args:
            scope: ASGI scope dict.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """

        response = JSONResponse(
            {
                "error": "Authentication required",
                "detail": "Admin access requires staff privileges.",
            },
            status_code=401,
        )
        await response(scope, receive, send)


def check_admin_access(request: Any) -> bool:
    """Check if a request has admin access.

    Args:
        request: The Request object.

    Returns:
        True if user has admin access.
    """
    user = getattr(request, "user", None)
    if user is None:
        return False

    if not getattr(user, "is_authenticated", False):
        return False

    return getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)


def check_model_permission(request: Any, model_class: Any, action: str) -> bool:
    """Check if user has permission for a model action.

    Args:
        request: The Request object.
        model_class: The model class.
        action: The action (view, add, change, delete).

    Returns:
        True if user has permission.
    """
    user = getattr(request, "user", None)
    if user is None:
        return False

    # Superusers have all permissions
    if getattr(user, "is_superuser", False):
        return True

    # Staff users have basic permissions
    if getattr(user, "is_staff", False):
        return True

    # Could implement granular permission checking here
    # e.g., user.has_perm(f"{model_class._app_name}.{action}_{model_class.__name__.lower()}")
    return False


def check_object_permission(request: Any, obj: Any, action: str) -> bool:
    """Check if user has permission for a specific object.

    Args:
        request: The Request object.
        obj: The model instance.
        action: The action (view, change, delete).

    Returns:
        True if user has permission.
    """
    user = getattr(request, "user", None)
    if user is None:
        return False

    # Superusers have all permissions
    if getattr(user, "is_superuser", False):
        return True

    # Staff users have basic permissions
    return bool(getattr(user, "is_staff", False))
