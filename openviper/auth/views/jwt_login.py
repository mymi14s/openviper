"""JWT login view - issues access and refresh tokens."""

from __future__ import annotations

from typing import TYPE_CHECKING

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

    async def post(self, request: Request, **kwargs: object) -> dict[str, str]:
        """Authenticate credentials and return a JWT access/refresh pair."""
        user = await self.authenticate_user(request)
        user_id = user.pk
        if user_id is None:
            raise ValueError("Authenticated users must have a primary key.")
        access = create_access_token(user_id=user_id)
        refresh = create_refresh_token(user_id=user_id)
        context = self.auth_hook_context(request, user, "jwt")
        context.token = {"type": "jwt", "issued": True}
        await self.run_on_login_hook(context)
        return {"access": access, "refresh": refresh}
