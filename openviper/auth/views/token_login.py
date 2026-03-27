"""Token login view — issues an opaque auth token."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from openviper.auth.authentications import create_token
from openviper.auth.views.base_login import BaseLoginView

if TYPE_CHECKING:
    from openviper.http.request import Request


class TokenLoginView(BaseLoginView):
    """Handle ``POST /auth/token/login``.

    Accepts ``{"username": "...", "password": "..."}`` and returns an opaque
    token on success.  The token should be included in subsequent requests as
    ``Authorization: Token <token>``.

    Response body::

        {"token": "<opaque-token>"}
    """

    async def post(self, request: Request, **kwargs: Any) -> dict[str, str]:
        """Authenticate credentials and return an opaque auth token."""
        user = await self.authenticate_user(request)
        raw, _ = await create_token(user_id=user.pk)
        return {"token": raw}
