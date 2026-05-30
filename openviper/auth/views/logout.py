"""Logout view - revokes the active credential (JWT, Token, or Session)."""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING, cast

from openviper.auth.authentications import (
    JWTAuthentication,
    SessionAuthentication,
    TokenAuthentication,
)
from openviper.auth.authentications import (
    revoke_token as revoke_opaque_token,
)
from openviper.auth.hooks import auth_hooks, build_auth_hook_context
from openviper.auth.jwt import decode_token_unverified
from openviper.auth.request_state import get_auth_state, set_auth_state
from openviper.auth.session.manager import SessionManager
from openviper.auth.token_blocklist import revoke_token as revoke_jwt_token
from openviper.exceptions import Unauthorized
from openviper.http.views import View

if TYPE_CHECKING:
    from openviper.auth.types import AuthPayload
    from openviper.http.request import Request

logger = logging.getLogger("openviper.auth.logout")


class LogoutView(View):
    """Handle ``POST /auth/logout``.

    Revokes the active credential based on the authentication type detected
    in ``request.auth``:

    - ``"jwt"`` - reads the raw token from the ``Authorization`` header,
      decodes it without verification (so expired tokens can still be
      blocklisted), and adds the ``jti`` to the JWT blocklist.
    - ``"token"`` - marks the opaque token inactive in the database.
    - ``"session"`` - deletes the session from the store and clears the
      session cookie.

    An unauthenticated request (``request.auth["type"] == "none"``) raises
    :class:`~openviper.exceptions.Unauthorized`.

    Response body::

        {"detail": "Logged out."}
    """

    authentication_classes = [JWTAuthentication, TokenAuthentication, SessionAuthentication]

    async def post(self, request: Request, **kwargs: object) -> dict[str, str]:
        """Revoke the current credential and return a confirmation message."""
        auth_info = cast("AuthPayload", getattr(request, "auth", None) or {})
        auth_type = str(auth_info.get("type", "none"))

        if auth_type == "none":
            raise Unauthorized("Authentication is required to log out.")

        context = build_auth_hook_context(
            user=getattr(request, "user", None),
            request=request,
            session=getattr(request, "session", getattr(request, "_session", None)),
            token={"type": auth_type, "present": bool(extract_auth_token(request, auth_type))},
            auth_backend=auth_type,
        )
        set_auth_state(request, "logout_hook_context", context)

        if auth_type == "jwt":
            await self.revoke_jwt(request)
        elif auth_type == "token":
            await self.revoke_opaque_token(request)
        elif auth_type == "session":
            await SessionManager().logout(request)
        else:
            logger.warning("LogoutView: unrecognised auth_type %r - skipping revocation", auth_type)

        if get_auth_state(request, "logout_hook_ran", False) is not True:
            await auth_hooks.run_on_logout(context)
        return {"detail": "Logged out."}

    async def revoke_jwt(self, request: Request) -> None:
        """Add the JWT jti to the blocklist."""
        raw_token = extract_auth_token(request, "jwt")
        if not raw_token:
            return

        claims = decode_token_unverified(raw_token)
        jti = claims.get("jti")
        if not isinstance(jti, str):
            return
        if not jti:
            return

        token_type = str(claims.get("type", "access"))
        raw_user_id = claims.get("sub")
        user_id = str(raw_user_id) if raw_user_id is not None else None

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

    async def revoke_opaque_token(self, request: Request) -> None:
        """Mark the opaque token inactive in the database."""
        raw_token = extract_auth_token(request, "token")
        if not raw_token:
            return
        await revoke_opaque_token(raw_token)


def extract_auth_token(request: Request, auth_type: str) -> str:
    """Return the raw credential from Authorization for logout only."""
    auth_header = request.headers.get("authorization", "")
    if not isinstance(auth_header, str):
        return ""
    if auth_type == "jwt" and auth_header.startswith("Bearer "):
        return auth_header[7:]
    if auth_type == "token" and auth_header.startswith("Token "):
        return auth_header[6:]
    return ""
