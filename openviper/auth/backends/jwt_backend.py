"""JWT authentication backend for OpenViper."""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING, cast

from jose import JWTError

from openviper.auth.jwt import decode_access_token_checked
from openviper.auth.token_blocklist import is_token_revoked
from openviper.auth.user import get_user_by_id
from openviper.exceptions import AuthenticationFailed, TokenExpired
from openviper.http.request import Request as HttpRequest

if TYPE_CHECKING:
    from openviper.auth.types import Authenticable

logger = logging.getLogger("openviper.auth.backends.jwt")


class JWTBackend:
    """Authenticate requests using JWT Bearer tokens.

    Accepts both a :class:`~openviper.http.request.Request` object (the normal
    dict (legacy / direct calls).
    """

    async def authenticate(
        self, scope: Authenticable | dict[str, Authenticable]
    ) -> tuple[Authenticable, dict[str, str]] | None:
        """Try to authenticate a request using a JWT Bearer token.

        Args:
            scope: Either a :class:`~openviper.http.request.Request` or a raw
                ASGI scope dict.

        Returns:
            ``(user, auth_info)`` on success, ``None`` if JWT auth does not
            apply or fails (allowing the next backend to try).
        """
        token = self.extract_token(scope)
        if token is None:
            return None

        try:
            payload_result = decode_access_token_checked(token)
            if inspect.isawaitable(payload_result):
                payload = await payload_result
            else:
                payload = payload_result
            jti_value = payload.get("jti")
            jti = jti_value if isinstance(jti_value, str) else None
            if jti and await is_token_revoked(jti):
                logger.debug("JWT token %s has been revoked", jti)
                return None

            user_id_value = payload.get("sub")
            user_id = user_id_value if isinstance(user_id_value, int | str) else None
            if not user_id:
                return None

            user = await get_user_by_id(user_id)
            if user and getattr(user, "is_active", True):
                return user, {"type": "jwt"}
        except TokenExpired:
            logger.debug(
                "JWT token expired for request to %s",
                getattr(scope, "path", scope.get("path") if isinstance(scope, dict) else "unknown"),
            )
        except (AuthenticationFailed, ValueError, KeyError, JWTError) as exc:
            logger.warning("JWT authentication error: %s", exc)

        return None

    def extract_token(self, scope: Authenticable | dict[str, Authenticable]) -> str | None:
        """Pull the raw JWT string from either a Request object or an ASGI scope dict."""
        if isinstance(scope, HttpRequest):
            auth_str = scope.headers.get("authorization") or ""
            if auth_str.startswith("Bearer "):
                return auth_str[7:]
            return None

        # Intent: Support direct ASGI scope callers that bypass the Request abstraction.
        if isinstance(scope, dict):
            headers = cast("list[tuple[bytes, bytes]]", scope.get("headers", []))
            auth_header = b""
            for name, value in headers:
                if name == b"authorization":
                    auth_header = value
                    break
            auth_str = auth_header.decode("latin-1") if auth_header else ""
            if auth_str.startswith("Bearer "):
                return auth_str[7:]
            return None

        return None
