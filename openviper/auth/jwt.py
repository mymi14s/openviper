"""JWT token creation and verification for OpenViper.

Uses ``python-jose`` under the hood with HS256 algorithm (RS256 configurable).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, cast

from jose import JWTError, jwt

from openviper.conf import settings
from openviper.exceptions import AuthenticationFailed, TokenExpired
from openviper.utils import timezone


def _secret() -> str:
    return getattr(settings, "SECRET_KEY", "fallback-secret-key")


def _algorithm() -> str:
    return getattr(settings, "JWT_ALGORITHM", "HS256")


def _access_expire() -> datetime.timedelta:
    return getattr(settings, "JWT_ACCESS_TOKEN_EXPIRE", datetime.timedelta(hours=24))


def _refresh_expire() -> datetime.timedelta:
    return getattr(settings, "JWT_REFRESH_TOKEN_EXPIRE", datetime.timedelta(days=7))


def create_access_token(
    user_id: int | str,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = timezone.now()
    expire = now + _access_expire()
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": expire,
        "type": "access",
    }
    if extra_claims:
        claims.update(extra_claims)
    return cast("str", jwt.encode(claims, _secret(), algorithm=_algorithm()))


def create_refresh_token(user_id: int | str) -> str:
    now = timezone.now()
    expire = now + _refresh_expire()
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": expire,
        "type": "refresh",
    }
    return cast("str", jwt.encode(claims, _secret(), algorithm=_algorithm()))


def decode_token_unverified(token: str) -> dict[str, Any]:
    """Return the claims from a JWT without verifying signature or expiry.

    Used only by the logout path to extract ``jti``/``exp`` so the token
    can be added to the blocklist even if it has already expired.

    Args:
        token: Encoded JWT string.

    Returns:
        Unverified claims dict, or an empty dict if the token is malformed.
    """
    try:
        return cast("dict[str, Any]", jwt.get_unverified_claims(token))
    except Exception:
        return {}


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT access token.

    Args:
        token: Encoded JWT string.

    Returns:
        Decoded claims dict.

    Raises:
        TokenExpired: Token has passed its expiry.
        AuthenticationFailed: Token is invalid or malformed.
    """
    try:
        payload = jwt.decode(token, _secret(), algorithms=[_algorithm()])
        if payload.get("type") != "access":
            raise AuthenticationFailed("Invalid token type.")
        return cast("dict[str, Any]", payload)
    except JWTError as exc:
        if "expired" in str(exc).lower():
            raise TokenExpired() from exc
        raise AuthenticationFailed(f"Invalid token: {exc}") from exc


def decode_refresh_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT refresh token.

    Args:
        token: Encoded JWT string.

    Returns:
        Decoded claims dict.

    Raises:
        TokenExpired: Token has passed its expiry.
        AuthenticationFailed: Token is invalid or malformed.
    """
    try:
        payload = jwt.decode(token, _secret(), algorithms=[_algorithm()])
        if payload.get("type") != "refresh":
            raise AuthenticationFailed("Invalid token type.")
        return cast("dict[str, Any]", payload)
    except JWTError as exc:
        if "expired" in str(exc).lower():
            raise TokenExpired() from exc
        raise AuthenticationFailed(f"Invalid token: {exc}") from exc
