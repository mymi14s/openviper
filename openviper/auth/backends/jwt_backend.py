"""JWT authentication backend for OpenViper."""

from __future__ import annotations

import logging
from typing import Any

from openviper.auth.jwt import decode_access_token
from openviper.auth.token_blocklist import is_token_revoked
from openviper.auth.user import get_user_by_id
from openviper.exceptions import TokenExpired

logger = logging.getLogger("openviper.auth.backends.jwt")


class JWTBackend:
    """Authenticate requests using JWT Bearer tokens.

    Reads the ``Authorization: Bearer <token>`` header, verifies the token,
    checks the revocation blocklist, and returns the authenticated user.
    """

    async def authenticate(self, scope: dict[str, Any]) -> tuple[Any, dict[str, Any]] | None:
        """Try to authenticate a request using a JWT Bearer token.

        Args:
            scope: ASGI connection scope containing request headers.

        Returns:
            ``(user, auth_info)`` on success, ``None`` if JWT auth does not apply
            or fails (allowing the next backend to try).
        """
        headers = scope.get("headers", [])
        auth_header = b""
        for name, value in headers:
            if name == b"authorization":
                auth_header = value
                break

        auth_str = auth_header.decode("latin-1") if auth_header else ""
        if not auth_str.startswith("Bearer "):
            return None

        token = auth_str[7:]
        try:

            payload = decode_access_token(token)
            jti = payload.get("jti")
            if jti and await is_token_revoked(jti):
                logger.debug("JWT token %s has been revoked", jti)
                return None

            user_id = payload.get("sub")
            if not user_id:
                return None

            user = await get_user_by_id(user_id)
            if user and getattr(user, "is_active", True):
                return user, {"type": "jwt", "token": token}
        except TokenExpired:
            logger.debug("JWT token expired for request to %s", scope.get("path"))
        except Exception as exc:
            logger.warning("JWT authentication error: %s", exc)

        return None
