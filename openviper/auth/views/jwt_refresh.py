"""JWT refresh view - exchanges a refresh token for a new access token."""

from __future__ import annotations

import datetime
import json
import logging
from typing import TYPE_CHECKING

from jose import JWTError

from openviper.auth.constants import JWT_GRANT_TYPE_REFRESH, MAX_TOKEN_LENGTH
from openviper.auth.jwt import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token_checked,
)
from openviper.auth.token_blocklist import revoke_token
from openviper.exceptions import AuthenticationFailed, TokenExpired, Unauthorized
from openviper.http.permissions import AllowAny
from openviper.http.views import View
from openviper.utils import timezone

if TYPE_CHECKING:
    from openviper.http.request import Request

logger = logging.getLogger("openviper.auth.jwt_refresh")


class JWTRefreshView(View):
    """Handle ``POST /auth/jwt/refresh``.

    Accepts ``{"refresh": "<refresh-token>"}`` and returns a new access token
    together with a freshly rotated refresh token.  The presented refresh
    token is verified and its ``jti`` is blocklisted immediately after use,
    enforcing single-use refresh token semantics.

    Response body::

        {
            "access": "<new-access-token>",
            "refresh": "<new-refresh-token>"
        }

    Raises :class:`~openviper.exceptions.Unauthorized` for missing, expired,
    revoked, or invalid refresh tokens.
    """

    permission_classes = [AllowAny]

    async def post(self, request: Request, **kwargs: object) -> dict[str, str]:
        """Validate the refresh token and issue a new access token."""
        try:
            body_raw = await request.json()
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise Unauthorized("Invalid request body.") from exc
        if not isinstance(body_raw, dict):
            raise Unauthorized("Invalid request body.")
        body: dict[str, object] = body_raw

        raw_token = str(body.get("refresh") or "").strip()
        if not raw_token:
            raise Unauthorized("Refresh token is required.")
        if len(raw_token) > MAX_TOKEN_LENGTH:
            raise Unauthorized("Refresh token exceeds maximum allowed length.")

        try:
            payload = await decode_refresh_token_checked(raw_token)
        except TokenExpired as exc:
            raise Unauthorized("Refresh token has expired.") from exc
        except (AuthenticationFailed, JWTError) as exc:
            raise Unauthorized("Invalid refresh token.") from exc

        user_id_value = payload.get("sub")
        if not isinstance(user_id_value, int | str) or not user_id_value:
            raise Unauthorized("Invalid refresh token.")

        jti_value = payload.get("jti")
        raw_exp = payload.get("exp")
        if isinstance(jti_value, str) and jti_value:
            if isinstance(raw_exp, (int, float)):
                expires_at = datetime.datetime.fromtimestamp(raw_exp, tz=datetime.UTC)
            elif isinstance(raw_exp, datetime.datetime):
                expires_at = raw_exp
            else:
                expires_at = timezone.now()

            await revoke_token(
                jti=jti_value,
                token_type=JWT_GRANT_TYPE_REFRESH,
                user_id=str(user_id_value),
                expires_at=expires_at,
            )

        access = create_access_token(user_id=user_id_value)
        refresh = create_refresh_token(user_id=user_id_value)
        return {"access": access, "refresh": refresh}
