"""Logout view — revokes the active credential (JWT, Token, or Session)."""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING, Any

from openviper.auth.authentications import (
    JWTAuthentication,
    SessionAuthentication,
    TokenAuthentication,
)
from openviper.auth.authentications import (
    revoke_token as revoke_opaque_token,
)
from openviper.auth.jwt import decode_token_unverified
from openviper.auth.session.manager import SessionManager
from openviper.auth.token_blocklist import revoke_token as revoke_jwt_token
from openviper.exceptions import Unauthorized
from openviper.http.views import View

if TYPE_CHECKING:
    from openviper.http.request import Request

logger = logging.getLogger("openviper.auth.logout")


class LogoutView(View):
    """Handle ``POST /auth/logout``.

    Revokes the active credential based on the authentication type detected
    in ``request.auth``:

    - ``"jwt"`` — reads the raw token from the ``Authorization`` header,
      decodes it without verification (so expired tokens can still be
      blocklisted), and adds the ``jti`` to the JWT blocklist.
    - ``"token"`` — marks the opaque token inactive in the database.
    - ``"session"`` — deletes the session from the store and clears the
      session cookie.

    An unauthenticated request (``request.auth["type"] == "none"``) raises
    :class:`~openviper.exceptions.Unauthorized`.

    Response body::

        {"detail": "Logged out."}
    """

    authentication_classes = [JWTAuthentication, TokenAuthentication, SessionAuthentication]

    async def post(self, request: Request, **kwargs: Any) -> dict[str, str]:
        """Revoke the current credential and return a confirmation message."""
        auth_info: dict[str, Any] = getattr(request, "auth", None) or {}
        auth_type: str = auth_info.get("type", "none")

        if auth_type == "none":
            raise Unauthorized("Authentication is required to log out.")

        if auth_type == "jwt":
            await self._revoke_jwt(auth_info)
        elif auth_type == "token":
            await self._revoke_opaque_token(auth_info)
        elif auth_type == "session":
            await SessionManager().logout(request)
        else:
            logger.warning("LogoutView: unrecognised auth_type %r — skipping revocation", auth_type)

        return {"detail": "Logged out."}

    async def _revoke_jwt(self, auth_info: dict[str, Any]) -> None:
        """Add the JWT jti to the blocklist."""
        raw_token: str = auth_info.get("token", "")
        if not raw_token:
            return

        claims = decode_token_unverified(raw_token)
        jti: str | None = claims.get("jti")
        if not jti:
            return

        token_type: str = claims.get("type", "access")
        user_id: str | None = claims.get("sub")

        raw_exp = claims.get("exp")
        if isinstance(raw_exp, (int, float)):
            expires_at = datetime.datetime.fromtimestamp(raw_exp, tz=datetime.UTC)
        elif isinstance(raw_exp, datetime.datetime):
            expires_at = raw_exp
        else:
            expires_at = datetime.datetime.now(tz=datetime.UTC)

        await revoke_jwt_token(
            jti=jti,
            token_type=token_type,
            user_id=user_id,
            expires_at=expires_at,
        )

    async def _revoke_opaque_token(self, auth_info: dict[str, Any]) -> None:
        """Mark the opaque token inactive in the database."""
        raw_token: str = auth_info.get("token", "")
        if not raw_token:
            return
        await revoke_opaque_token(raw_token)
