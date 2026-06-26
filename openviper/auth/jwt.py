"""JWT token creation and verification for OpenViper.

Uses ``python-jose`` under the hood with HS256 algorithm (RS256 configurable).
"""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING, cast

from jose import ExpiredSignatureError, JWTError, jwt

from openviper.auth.constants import ALLOWED_JWT_ALGORITHMS, ASYMMETRIC_PREFIXES
from openviper.auth.token_blocklist import is_token_known_revoked, is_token_revoked
from openviper.conf import settings
from openviper.exceptions import AuthenticationFailed, TokenExpired
from openviper.utils import timezone

if TYPE_CHECKING:
    from openviper.auth.types import AuthPayload


def get_jwt_config() -> tuple[str, str]:
    """Return (secret_key, algorithm) from settings, validating they are set.

    This is called lazily by JWT functions to avoid crashing during early
    framework import if SECRET_KEY is not yet configured.
    """
    secret = getattr(settings, "SECRET_KEY", "")
    if not secret:
        raise RuntimeError(
            "SECRET_KEY must be configured in settings before using JWT tokens. "
            "Never use a fallback secret key for security reasons."
        )

    algo = getattr(settings, "JWT_ALGORITHM", "HS256")
    if algo not in ALLOWED_JWT_ALGORITHMS:
        raise RuntimeError(
            f"Insecure JWT algorithm {algo!r} is not allowed. "
            f"Use one of: {', '.join(sorted(ALLOWED_JWT_ALGORITHMS))}"
        )

    if algo[:2] in ASYMMETRIC_PREFIXES and not secret.strip().startswith("-----"):
        raise RuntimeError(
            f"JWT algorithm {algo!r} requires a PEM-formatted key, "
            "but SECRET_KEY does not appear to be in PEM format. "
            "Set SECRET_KEY to a valid PEM private key or use an HMAC algorithm (HS256)."
        )

    return secret, algo


def as_timedelta(
    value: datetime.timedelta | int, default: datetime.timedelta
) -> datetime.timedelta:
    if isinstance(value, datetime.timedelta):
        return value
    if isinstance(value, int):
        return datetime.timedelta(seconds=value)
    return default


def jwt_access_expire() -> datetime.timedelta:
    return as_timedelta(
        getattr(settings, "JWT_ACCESS_TOKEN_EXPIRE", datetime.timedelta(hours=24)),
        datetime.timedelta(hours=24),
    )


def jwt_refresh_expire() -> datetime.timedelta:
    return as_timedelta(
        getattr(settings, "JWT_REFRESH_TOKEN_EXPIRE", datetime.timedelta(days=7)),
        datetime.timedelta(days=7),
    )


def create_access_token(
    user_id: int | str,
    extra_claims: AuthPayload | None = None,
    expires_delta: datetime.timedelta | None = None,
) -> str:
    """Create a JWT access token.

    Args:
        user_id: The user ID to encode in the token.
        extra_claims: Additional claims to include in the token.
        expires_delta: Custom expiration time. If None, uses the default from settings.

    Returns:
        Encoded JWT token string.
    """
    now = timezone.now()
    expire = now + (expires_delta if expires_delta is not None else jwt_access_expire())
    core_claims: AuthPayload = {
        "sub": str(user_id),
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": expire,
        "type": "access",
    }
    claims: AuthPayload = {**(extra_claims or {}), **core_claims}
    secret, algo = get_jwt_config()
    return cast("str", jwt.encode(claims, secret, algorithm=algo))


def create_refresh_token(user_id: int | str) -> str:
    now = timezone.now()
    expire = now + jwt_refresh_expire()
    claims: AuthPayload = {
        "sub": str(user_id),
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": expire,
        "type": "refresh",
    }
    secret, algo = get_jwt_config()
    return cast("str", jwt.encode(claims, secret, algorithm=algo))


def decode_token_unverified(token: str) -> AuthPayload:
    """Return the claims from a JWT without verifying signature or expiry.

    Used only by the logout path to extract ``jti``/``exp`` so the token
    can be added to the blocklist even if it has already expired.

    Args:
        token: Encoded JWT string.

    Returns:
        Unverified claims dict, or an empty dict if the token is malformed.
    """
    try:
        return cast("AuthPayload", jwt.get_unverified_claims(token))
    except JWTError:
        return {}


def decode_access_token(token: str) -> AuthPayload:
    """Decode and verify a JWT access token.

    Args:
        token: Encoded JWT string.

    Returns:
        Decoded claims dict.

    Raises:
        TokenExpired: Token has passed its expiry.
        AuthenticationFailed: Token is invalid or malformed.
    """
    secret, algo = get_jwt_config()
    try:
        payload = jwt.decode(token, secret, algorithms=[algo])
        if payload.get("type") != "access":
            raise AuthenticationFailed("Invalid token type.")
        jti = payload.get("jti")
        if isinstance(jti, str) and is_token_known_revoked(jti):
            raise AuthenticationFailed("Invalid token.")
        return cast("AuthPayload", payload)
    except ExpiredSignatureError as exc:
        raise TokenExpired() from exc
    except JWTError as exc:
        # Keep token parser details out of client-facing errors.
        raise AuthenticationFailed("Invalid token.") from exc


async def decode_access_token_checked(token: str) -> AuthPayload:
    """Decode an access token and reject blocklisted token IDs."""
    payload = decode_access_token(token)
    jti = payload.get("jti")
    if isinstance(jti, str) and await is_token_revoked(jti):
        raise AuthenticationFailed("Invalid token.")
    return payload


def decode_refresh_token(token: str) -> AuthPayload:
    """Decode and verify a JWT refresh token.

    Args:
        token: Encoded JWT string.

    Returns:
        Decoded claims dict.

    Raises:
        TokenExpired: Token has passed its expiry.
        AuthenticationFailed: Token is invalid or malformed.
    """
    secret, algo = get_jwt_config()
    try:
        payload = jwt.decode(token, secret, algorithms=[algo])
        if payload.get("type") != "refresh":
            raise AuthenticationFailed("Invalid token type.")
        jti = payload.get("jti")
        if isinstance(jti, str) and is_token_known_revoked(jti):
            raise AuthenticationFailed("Invalid token.")
        return cast("AuthPayload", payload)
    except ExpiredSignatureError as exc:
        raise TokenExpired() from exc
    except JWTError as exc:
        # Keep token parser details out of client-facing errors.
        raise AuthenticationFailed("Invalid token.") from exc


async def decode_refresh_token_checked(token: str) -> AuthPayload:
    """Decode a refresh token and reject blocklisted token IDs."""
    payload = decode_refresh_token(token)
    jti = payload.get("jti")
    if isinstance(jti, str) and await is_token_revoked(jti):
        raise AuthenticationFailed("Invalid token.")
    return payload
