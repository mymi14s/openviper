"""JWT authentication backend for OpenViper."""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

from openviper.auth.jwt import decode_access_token
from openviper.auth.token_blocklist import is_token_revoked
from openviper.auth.user import get_user_by_id
from openviper.exceptions import TokenExpired
from openviper.http.request import Request as _HttpRequest

logger = logging.getLogger("openviper.auth.backends.jwt")


class JWTBackend:
    """Authenticate requests using JWT Bearer tokens.

    Reads the ``Authorization: Bearer <token>`` header, or falls back to the

    Accepts both a :class:`~openviper.http.request.Request` object (the normal
    dict (legacy / direct calls).
    """

    async def authenticate(self, scope: Any) -> tuple[Any, dict[str, Any]] | None:
        """Try to authenticate a request using a JWT Bearer token.

        Args:
            scope: Either a :class:`~openviper.http.request.Request` or a raw
                ASGI scope dict.

        Returns:
            ``(user, auth_info)`` on success, ``None`` if JWT auth does not
            apply or fails (allowing the next backend to try).
        """
        token = self._extract_token(scope)
        if token is None:
            return None

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
            logger.debug(
                "JWT token expired for request to %s",
                getattr(scope, "path", scope.get("path") if isinstance(scope, dict) else "unknown"),
            )
        except Exception as exc:
            logger.warning("JWT authentication error: %s", exc)

        return None

    def _extract_token(self, scope: Any) -> str | None:
        """Pull the raw JWT string from either a Request object or an ASGI scope dict."""
        if isinstance(scope, _HttpRequest):
            auth_str = scope.headers.get("authorization") or ""
            if auth_str.startswith("Bearer "):
                return auth_str[7:]
            # send custom headers during the handshake).
            return scope.query_params.get("token") or None

        # Raw ASGI scope dict path (legacy / direct callers)
        if isinstance(scope, dict):
            headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
            auth_header = b""
            for name, value in headers:
                if name == b"authorization":
                    auth_header = value
                    break
            auth_str = auth_header.decode("latin-1") if auth_header else ""
            if auth_str.startswith("Bearer "):
                return auth_str[7:]
            query_string = scope.get("query_string", b"")
            params = urllib.parse.parse_qs(query_string.decode("latin-1"))
            token_list = params.get("token", [])
            return token_list[0] if token_list else None

        return None
