"""JWT login view — issues access and refresh tokens."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from openviper.auth.jwt import create_access_token, create_refresh_token
from openviper.auth.views.base_login import BaseLoginView

if TYPE_CHECKING:
    from openviper.http.request import Request


class JWTLoginView(BaseLoginView):
    """Handle ``POST /auth/jwt/login``.

    Accepts ``{"username": "...", "password": "..."}`` and returns a pair of
    JWT tokens on success.

    Response body::

        {
            "access":  "<access-token>",
            "refresh": "<refresh-token>"
        }
    """

    async def post(self, request: Request, **kwargs: Any) -> dict[str, str]:
        """Authenticate credentials and return a JWT access/refresh pair."""
        user = await self.authenticate_user(request)
        access = create_access_token(user_id=user.pk)
        refresh = create_refresh_token(user_id=user.pk)
        return {"access": access, "refresh": refresh}
