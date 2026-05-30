"""Admin authentication and permission middleware.

Provides middleware to protect admin routes and ensure only
authorized staff users can access the admin panel.
"""

from __future__ import annotations

import typing as t
from urllib.parse import unquote

from openviper.admin.api.permissions import (
    PermissionChecker,
    check_admin_access,
    check_model_permission,
    check_object_permission,
)
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
        "/admin/api/auth/logout/",
        "/admin/api/config/",
    ]

    async def __call__(self, scope: dict[str, t.Any], receive: t.Any, send: t.Any) -> None:
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
        # Normalize: decode percent-encoding, collapse double slashes,
        # and reject path-traversal segments before prefix matching.
        normalized_path = unquote(path)
        normalized_path = normalized_path.replace("//", "/")
        if "/../" in normalized_path or normalized_path.endswith("/.."):
            await self.send_unauthorized(scope, receive, send)
            return
        normalized_path = normalized_path.rstrip("/") + "/"

        if not normalized_path.startswith(self.ADMIN_PATH_PREFIX):
            await self.app(scope, receive, send)
            return

        if normalized_path in self.EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        if not await self.check_admin_authentication(scope):
            await self.send_unauthorized(scope, receive, send)
            return

        await self.app(scope, receive, send)

    async def check_admin_authentication(self, scope: dict[str, t.Any]) -> bool:
        """Check if the request is authenticated for admin access.

        Args:
            scope: ASGI scope dict.

        Returns:
            True if user is authenticated and is staff/superuser.
        """
        user = scope.get("user")
        if user is None:
            return False

        if not getattr(user, "is_authenticated", False):
            return False

        is_staff = getattr(user, "is_staff", False)
        is_superuser = getattr(user, "is_superuser", False)

        return is_staff or is_superuser

    async def send_unauthorized(self, scope: dict[str, t.Any], receive: t.Any, send: t.Any) -> None:
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


__all__ = [
    "AdminMiddleware",
    "PermissionChecker",
    "check_admin_access",
    "check_model_permission",
    "check_object_permission",
]
