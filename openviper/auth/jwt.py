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

# Cache JWT settings at module level to avoid repeated attribute lookups
# Fail fast if SECRET_KEY is not configured
if not hasattr(settings, "SECRET_KEY") or not settings.SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY must be configured in settings before using JWT tokens. "
        "Never use a fallback secret key for security reasons."
    )
_JWT_SECRET: str = settings.SECRET_KEY

# Whitelist of secure JWT algorithms (prevents "none" algorithm attack)
_ALLOWED_JWT_ALGORITHMS: frozenset[str] = frozenset(
    {
        "HS256",
        "HS384",
        "HS512",  # HMAC with SHA-2
        "RS256",
        "RS384",
        "RS512",  # RSA with SHA-2
        "ES256",
        "ES384",
        "ES512",  # ECDSA with SHA-2
        "PS256",
        "PS384",
        "PS512",  # RSA-PSS with SHA-2
    }
)

_JWT_ALGORITHM: str = getattr(settings, "JWT_ALGORITHM", "HS256")
if _JWT_ALGORITHM not in _ALLOWED_JWT_ALGORITHMS:
    raise RuntimeError(
        f"Insecure JWT algorithm '{_JWT_ALGORITHM}' is not allowed. "
        f"Use one of: {', '.join(sorted(_ALLOWED_JWT_ALGORITHMS))}"
    )

# Asymmetric algorithms require PEM-formatted keys
_ASYMMETRIC_PREFIXES: frozenset[str] = frozenset({"RS", "ES", "PS"})
if _JWT_ALGORITHM[:2] in _ASYMMETRIC_PREFIXES and not _JWT_SECRET.strip().startswith("-----"):
    raise RuntimeError(
        f"JWT algorithm '{_JWT_ALGORITHM}' requires a PEM-formatted key, "
        "but SECRET_KEY does not appear to be in PEM format. "
        "Set SECRET_KEY to a valid PEM private key or use an HMAC algorithm (HS256)."
    )


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
    return cast("str", jwt.encode(claims, _JWT_SECRET, algorithm=_JWT_ALGORITHM))


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
    return cast("str", jwt.encode(claims, _JWT_SECRET, algorithm=_JWT_ALGORITHM))


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
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
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
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise AuthenticationFailed("Invalid token type.")
        return cast("dict[str, Any]", payload)
    except ExpiredSignatureError as exc:
        raise TokenExpired() from exc
    except JWTError as exc:
        # Do not include exc details — internal parsing errors can reveal
        # structural information about the token to an attacker.
        raise AuthenticationFailed("Invalid token.") from exc
