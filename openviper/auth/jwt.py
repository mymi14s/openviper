"""JWT token creation and verification for OpenViper.

Uses ``python-jose`` under the hood with HS256 algorithm (RS256 configurable).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, cast

from jose import ExpiredSignatureError, JWTError, jwt

from openviper.conf import settings
from openviper.exceptions import AuthenticationFailed, TokenExpired
from openviper.utils import timezone

# Whitelist of secure JWT algorithms (prevents "none" algorithm attack)
_ALLOWED_JWT_ALGORITHMS: frozenset[str] = frozenset(
    {
        "HS256",
        "HS384",
        "HS512",
        "RS256",
        "RS384",
        "RS512",
        "ES256",
        "ES384",
        "ES512",
        "PS256",
        "PS384",
        "PS512",
    }
)

# Asymmetric algorithms require PEM-formatted keys
_ASYMMETRIC_PREFIXES: frozenset[str] = frozenset({"RS", "ES", "PS"})


def _get_jwt_config() -> tuple[str, str]:
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
    if algo not in _ALLOWED_JWT_ALGORITHMS:
        raise RuntimeError(
            f"Insecure JWT algorithm {algo!r} is not allowed. "
            f"Use one of: {', '.join(sorted(_ALLOWED_JWT_ALGORITHMS))}"
        )

    # Asymmetric algorithms require PEM-formatted keys
    if algo[:2] in _ASYMMETRIC_PREFIXES and not secret.strip().startswith("-----"):
        raise RuntimeError(
            f"JWT algorithm {algo!r} requires a PEM-formatted key, "
            "but SECRET_KEY does not appear to be in PEM format. "
            "Set SECRET_KEY to a valid PEM private key or use an HMAC algorithm (HS256)."
        )

    return secret, algo


def _as_timedelta(
    value: datetime.timedelta | int, default: datetime.timedelta
) -> datetime.timedelta:
    if isinstance(value, datetime.timedelta):
        return value
    if isinstance(value, int):
        return datetime.timedelta(seconds=value)
    return default


_JWT_ACCESS_EXPIRE: datetime.timedelta = _as_timedelta(
    getattr(settings, "JWT_ACCESS_TOKEN_EXPIRE", datetime.timedelta(hours=24)),
    datetime.timedelta(hours=24),
)
_JWT_REFRESH_EXPIRE: datetime.timedelta = _as_timedelta(
    getattr(settings, "JWT_REFRESH_TOKEN_EXPIRE", datetime.timedelta(days=7)),
    datetime.timedelta(days=7),
)


def create_access_token(
    user_id: int | str,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = timezone.now()
    expire = now + _JWT_ACCESS_EXPIRE
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": expire,
        "type": "access",
    }
    if extra_claims:
        claims.update(extra_claims)
    secret, algo = _get_jwt_config()
    return cast("str", jwt.encode(claims, secret, algorithm=algo))


def create_refresh_token(user_id: int | str) -> str:
    now = timezone.now()
    expire = now + _JWT_REFRESH_EXPIRE
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": expire,
        "type": "refresh",
    }
    secret, algo = _get_jwt_config()
    return cast("str", jwt.encode(claims, secret, algorithm=algo))


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
    except JWTError:
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
    secret, algo = _get_jwt_config()
    try:
        payload = jwt.decode(token, secret, algorithms=[algo])
        if payload.get("type") != "access":
            raise AuthenticationFailed("Invalid token type.")
        return cast("dict[str, Any]", payload)
    except ExpiredSignatureError as exc:
        raise TokenExpired() from exc
    except JWTError as exc:
        # Do not include exc details in the message — internal parsing errors
        # can reveal structural information about the token to an attacker.
        raise AuthenticationFailed("Invalid token.") from exc


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
    secret, algo = _get_jwt_config()
    try:
        payload = jwt.decode(token, secret, algorithms=[algo])
        if payload.get("type") != "refresh":
            raise AuthenticationFailed("Invalid token type.")
        return cast("dict[str, Any]", payload)
    except ExpiredSignatureError as exc:
        raise TokenExpired() from exc
    except JWTError as exc:
        # Do not include exc details — internal parsing errors can reveal
        # structural information about the token to an attacker.
        raise AuthenticationFailed("Invalid token.") from exc
