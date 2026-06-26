"""Centralised constant definitions for the OpenViper authentication module."""

from __future__ import annotations

from typing import Final

# JWT algorithm security allowlist - prevents the "none" algorithm attack.
ALLOWED_JWT_ALGORITHMS: frozenset[str] = frozenset(
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

# Algorithms whose keys are asymmetric key pairs (PEM), not a shared secret.
ASYMMETRIC_PREFIXES: frozenset[str] = frozenset({"RS", "ES", "PS"})

# Per-request user resolution cache - short TTL balances freshness with performance.
USER_CACHE_TTL: Final[float] = 30.0
USER_CACHE_MAXSIZE: Final[int] = 4096

# Opaque token cache - longer TTL since tokens change infrequently.
TOKEN_CACHE_TTL: Final[float] = 600.0
TOKEN_CACHE_MAXSIZE: Final[int] = 4096

API_KEY_CACHE_TTL: Final[float] = 600.0
API_KEY_CACHE_MAXSIZE: Final[int] = 4096

# JWT blocklist dual cache - short negative TTL ensures revocations propagate quickly.
BLOCKLIST_CACHE_MAXSIZE: Final[int] = 8192
BLOCKLIST_NEGATIVE_CACHE_TTL: Final[float] = 10.0

CT_PERMISSION_CACHE_MAXSIZE: Final[int] = 4096

# CR/LF characters used to reject header injection in cookie values.
CRLF_CHARS: frozenset[str] = frozenset("\r\n")

# Session cache key prefixes for cache-through session storage.
SESSION_CACHE_PREFIX: str = "session:"
SESSION_USER_CACHE_PREFIX: str = "session_user:"

MAX_TOKEN_LENGTH: Final[int] = 8192
MAX_CREDENTIAL_FIELD_LENGTH: Final[int] = 512

OAUTH2_STATE_COOKIE: str = "oauth2_state"
OAUTH2_STATE_MAX_AGE: Final[int] = 600
OAUTH2_HTTPX_TIMEOUT: Final[float] = 10.0
OAUTH2_EVENT_NAMES: frozenset[str] = frozenset(
    {"on_success", "on_fail", "on_error", "on_initial"}
)

# JWT claim type identifiers - distinguish access grants from refresh grants.
JWT_GRANT_TYPE_ACCESS: str = "access"
JWT_GRANT_TYPE_REFRESH: str = "refresh"

# Credential fields that must be redacted from logs and hook context payloads.
SENSITIVE_CREDENTIAL_FIELDS: frozenset[str] = frozenset(
    {
        "password",
        "password_confirm",
        "otp",
        "totp",
        "secret",
        "token",
        "refresh_token",
        "access_token",
        "api_key",
    }
)

# ASGI scope key for per-request authentication state storage.
AUTH_STATE_KEY: str = "openviper.auth"

__all__ = [
    "ALLOWED_JWT_ALGORITHMS",
    "ASYMMETRIC_PREFIXES",
    "USER_CACHE_TTL",
    "USER_CACHE_MAXSIZE",
    "TOKEN_CACHE_TTL",
    "TOKEN_CACHE_MAXSIZE",
    "API_KEY_CACHE_TTL",
    "API_KEY_CACHE_MAXSIZE",
    "BLOCKLIST_CACHE_MAXSIZE",
    "BLOCKLIST_NEGATIVE_CACHE_TTL",
    "CT_PERMISSION_CACHE_MAXSIZE",
    "CRLF_CHARS",
    "SESSION_CACHE_PREFIX",
    "SESSION_USER_CACHE_PREFIX",
    "MAX_TOKEN_LENGTH",
    "MAX_CREDENTIAL_FIELD_LENGTH",
    "JWT_GRANT_TYPE_ACCESS",
    "JWT_GRANT_TYPE_REFRESH",
    "OAUTH2_STATE_COOKIE",
    "OAUTH2_STATE_MAX_AGE",
    "OAUTH2_HTTPX_TIMEOUT",
    "OAUTH2_EVENT_NAMES",
    "SENSITIVE_CREDENTIAL_FIELDS",
    "AUTH_STATE_KEY",
]
