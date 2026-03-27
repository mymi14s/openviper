"""Me view — returns the profile of the authenticated user."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from openviper.auth.authentications import (
    JWTAuthentication,
    SessionAuthentication,
    TokenAuthentication,
)
from openviper.exceptions import Unauthorized
from openviper.http.views import View

if TYPE_CHECKING:
    from openviper.http.request import Request


class MeView(View):
    """Handle ``GET /auth/me``.

    Returns basic profile information for the currently authenticated user.
    All built-in authentication schemes (JWT, Token, Session) are accepted.

    Response body::

        {
            "id":           1,
            "username":     "alice",
            "email":        "alice@example.com",
            "first_name":   "Alice",
            "last_name":    "Liddell",
            "is_active":    true,
            "is_staff":     false,
            "is_superuser": false
        }

    Raises :class:`~openviper.exceptions.Unauthorized` for anonymous requests.
    """

    authentication_classes = [JWTAuthentication, TokenAuthentication, SessionAuthentication]

    async def get(self, request: Request, **kwargs: Any) -> dict[str, Any]:
        """Return the authenticated user's profile."""
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            raise Unauthorized("Authentication is required.")

        return {
            "id": getattr(user, "pk", None),
            "username": getattr(user, "username", None),
            "email": getattr(user, "email", None),
            "first_name": getattr(user, "first_name", None),
            "last_name": getattr(user, "last_name", None),
            "is_active": getattr(user, "is_active", True),
            "is_staff": getattr(user, "is_staff", False),
            "is_superuser": getattr(user, "is_superuser", False),
        }
