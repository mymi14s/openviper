"""Authentication schemes and opaque-token storage for OpenViper.

Contains all three built-in authentication backends (JWT, Token, Session),
the shared TTL user cache, and the opaque-token lifecycle helpers
(``create_token``, ``revoke_token``, ``clear_token_auth_cache``).

Token values are never stored in plain text.  Only the SHA-256 hex-digest of
each token is persisted; the raw value is returned once by :func:`create_token`
and cannot be recovered afterwards.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import inspect
import logging
import re
import secrets
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Final, cast

import sqlalchemy as sa
from jose import JWTError

from openviper.auth._cache_utils import ensure_table, evict_cache_if_full, lazy_async_lock
from openviper.auth._user_cache import USER_CACHE, get_user_cache_lock
from openviper.auth.jwt import decode_access_token, decode_access_token_checked
from openviper.auth.session.store import get_session_store
from openviper.auth.token_blocklist import is_token_revoked
from openviper.auth.user import get_user_by_id
from openviper.conf import settings
from openviper.db.connection import get_engine, get_metadata
from openviper.exceptions import AuthenticationFailed, TokenExpired
from openviper.utils import timezone
from openviper.utils.importlib import import_string_uncached

if TYPE_CHECKING:
    from openviper.auth.types import Authenticable, AuthPayload
    from openviper.http.request import Request

logger = logging.getLogger("openviper.auth")

USER_CACHE_TTL: Final[float] = 30.0
USER_CACHE_MAXSIZE: Final[int] = 4096
OAuth2EventHandler = Callable[["AuthPayload"], object]


async def get_user_cached(user_id: int | str) -> Authenticable | None:
    """Fetch a user by ID, honouring a 30 s in-process TTL cache."""
    now = time.monotonic()
    lock = get_user_cache_lock()

    async with lock:
        entry = USER_CACHE.get(user_id)
        if entry is not None:
            user, expires_at = entry
            if now < expires_at:
                return user
            del USER_CACHE[user_id]

    user = await get_user_by_id(user_id)

    async with lock:
        if len(USER_CACHE) >= USER_CACHE_MAXSIZE:
            evict_now = time.monotonic()
            batch = max(1, int(USER_CACHE_MAXSIZE * 0.1))
            stale = [k for k, (_, exp) in USER_CACHE.items() if exp < evict_now][:batch]
            if not stale:
                stale = list(USER_CACHE.keys())[:batch]
            for k in stale:
                del USER_CACHE[k]
        USER_CACHE[user_id] = (user, time.monotonic() + USER_CACHE_TTL)

    return user


class BaseAuthentication(ABC):
    """Base class for all authentication schemes."""

    @abstractmethod
    async def authenticate(self, request: Request) -> tuple[Authenticable, AuthPayload] | None:
        """Authenticate the request and return a (user, auth_info) pair.

        Return None if authentication is not performed.
        """
        ...

    def authenticate_header(self, request: Request) -> str | None:
        """
        Return a string to be used as the value of the WWW-Authenticate
        header in a 401 response.
        """
        return None


class JWTAuthentication(BaseAuthentication):
    """Token based authentication using JSON Web Tokens."""

    async def authenticate(self, request: Request) -> tuple[Authenticable, AuthPayload] | None:
        auth_header: str | None = request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token: str | None = auth_header[7:]
        else:
            token = None

        if not token:
            return None
        try:
            payload = decode_access_token(token)
            jti_value = payload.get("jti")
            jti = jti_value if isinstance(jti_value, str) else None
            if jti and await is_token_revoked(jti):
                return None

            user_id_value = payload.get("sub")
            user_id = user_id_value if isinstance(user_id_value, int | str) else None
            if user_id:
                user = await get_user_cached(user_id)
                if user and user.is_active:
                    return user, {"type": "jwt"}
        except TokenExpired:
            logger.debug("JWT token expired for request to %s", request.path)
        except AuthenticationFailed, ValueError, KeyError, JWTError:
            pass

        return None

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"


class SessionAuthentication(BaseAuthentication):
    """Use session-based authentication."""

    async def authenticate(self, request: Request) -> tuple[Authenticable, AuthPayload] | None:
        """Authenticate using the session attached by SessionMiddleware.

        Fast path: if SessionMiddleware already loaded an authenticated user
        into ``scope["user"]``, return it immediately without a DB query.
        Fallback: resolve the user from the session store, loading from cookie
        if SessionMiddleware is not in the middleware stack.
        """
        scope_user = getattr(request, "_scope", {}).get("user")
        if (
            scope_user is not None
            and getattr(scope_user, "is_authenticated", False)
            and getattr(scope_user, "is_active", True)
        ):
            return scope_user, {"type": "session"}

        session = request.session
        session_key = session.key if session and not session.is_empty else None

        # Fall back to direct cookie parsing so SessionAuthentication
        # works without SessionMiddleware having run first.
        if not session_key:
            cookie_name = getattr(settings, "SESSION_COOKIE_NAME", "sessionid")
            session_key = request.cookies.get(cookie_name)

        if not session_key:
            return None

        try:
            store = get_session_store()

            user = await store.get_user(session_key)
            if user and getattr(user, "is_active", True):
                return user, {"type": "session"}
        except (ValueError, KeyError, LookupError) as exc:
            logger.warning("Session authentication error: %s", exc)

        return None


AUTH_TOKENS_TABLE_REF: list[sa.Table | None] = [None]
_AUTH_TOKENS_ENSURED: list[bool] = [False]
TABLE_ENSURE_LOCK: asyncio.Lock = asyncio.Lock()

TOKEN_CACHE: dict[str, tuple[int, float]] = {}
_TOKEN_CACHE_LOCK_REF: list[asyncio.Lock | None] = [None]
TOKEN_CACHE_TTL: Final[float] = 600.0
TOKEN_CACHE_MAXSIZE: Final[int] = 4096
TOKEN_LOCK_INIT_GUARD: threading.Lock = threading.Lock()


def get_token_cache_lock() -> asyncio.Lock:
    """Return the module-level token cache lock, creating it lazily."""
    return lazy_async_lock(_TOKEN_CACHE_LOCK_REF, TOKEN_LOCK_INIT_GUARD)


def hash_token(raw: str) -> str:
    """Return the SHA-256 hex-digest of *raw*."""
    return hashlib.sha256(raw.encode()).hexdigest()


def evict_token_cache_if_full(now: float) -> None:
    """Evict stale then oldest entries when the token cache is at capacity.

    Must be called while holding the token cache lock.
    """
    evict_cache_if_full(TOKEN_CACHE, TOKEN_CACHE_MAXSIZE, now, lambda v: v[1])


def get_auth_tokens_table() -> sa.Table:
    """Return the ``auth_tokens`` SA ``Table``, creating it once if needed."""
    if AUTH_TOKENS_TABLE_REF[0] is None:
        meta = get_metadata()
        AUTH_TOKENS_TABLE_REF[0] = sa.Table(
            "auth_tokens",
            meta,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("user_id", sa.Integer, nullable=False, index=True),
            sa.Column("created_at", sa.DateTime, nullable=True),
            sa.Column("expires_at", sa.DateTime, nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False, default=True),
            extend_existing=True,
        )
    table = AUTH_TOKENS_TABLE_REF[0]
    if table is None:
        raise RuntimeError("Auth tokens table initialization failed.")
    return table


async def ensure_auth_tokens_table() -> None:
    """Create the ``auth_tokens`` table if it does not yet exist."""
    table = get_auth_tokens_table()
    await ensure_table(table, _AUTH_TOKENS_ENSURED, TABLE_ENSURE_LOCK)


async def create_token(
    user_id: int, expires_at: datetime.datetime | None = None
) -> tuple[str, AuthPayload]:
    """Generate a new opaque auth token for *user_id*.

    The raw token value is returned exactly once and is NOT stored.  Only its
    SHA-256 hash is persisted.  Callers must save the raw value immediately.

    Args:
        user_id: Primary key of the user that owns the token.
        expires_at: Optional :class:`datetime.datetime` (UTC) when the token
            expires.  ``None`` means the token never expires.

    Returns:
        A 2-tuple ``(raw_token, record)`` where *record* is a plain ``dict``
        representation of the created row.
    """
    await ensure_auth_tokens_table()
    raw = secrets.token_hex(20)  # 40-char hex string, cryptographically random
    key_hash = hash_token(raw)
    now_utc = timezone.now()
    table = get_auth_tokens_table()
    engine = await get_engine()

    async with engine.begin() as conn:
        stmt = (
            sa.insert(table)
            .values(
                key_hash=key_hash,
                user_id=user_id,
                created_at=now_utc,
                expires_at=expires_at,
                is_active=True,
            )
            .returning(
                table.c.id,
                table.c.key_hash,
                table.c.user_id,
                table.c.created_at,
                table.c.expires_at,
                table.c.is_active,
            )
        )
        row = (await conn.execute(stmt)).one()

    record: AuthPayload = {
        "id": row.id,
        "key_hash": row.key_hash,
        "user_id": row.user_id,
        "created_at": row.created_at,
        "expires_at": row.expires_at,
        "is_active": row.is_active,
    }
    logger.debug("Created auth token for user_id=%s", user_id)
    return raw, record


async def revoke_token(raw: str) -> None:
    """Revoke the token with the given raw value.

    Marks the row ``is_active = False`` in the database and evicts the
    corresponding entry from the in-process cache so that the revocation
    takes effect immediately within this process.

    Args:
        raw: The original raw token string (not the hash).
    """
    await ensure_auth_tokens_table()
    key_hash = hash_token(raw)
    table = get_auth_tokens_table()
    engine = await get_engine()

    async with engine.begin() as conn:
        await conn.execute(
            sa.update(table).where(table.c.key_hash == key_hash).values(is_active=False)
        )

    lock = get_token_cache_lock()
    async with lock:
        TOKEN_CACHE.pop(key_hash, None)

    logger.debug("Revoked auth token (hash prefix %s\u2026)", key_hash[:8])


def clear_token_auth_cache() -> None:
    """Clear the in-process token cache.  Intended for tests and clean shutdown."""
    TOKEN_CACHE.clear()


API_KEYS_TABLE_REF: list[sa.Table | None] = [None]
_API_KEYS_ENSURED: list[bool] = [False]
API_KEYS_ENSURE_LOCK: asyncio.Lock = asyncio.Lock()

API_KEY_CACHE: dict[str, tuple[int, str, float]] = {}
API_KEY_CACHE_TTL: Final[float] = 600.0
API_KEY_CACHE_MAXSIZE: Final[int] = 4096
_API_KEY_CACHE_LOCK_REF: list[asyncio.Lock | None] = [None]
API_KEY_LOCK_INIT_GUARD: threading.Lock = threading.Lock()


def get_api_key_cache_lock() -> asyncio.Lock:
    """Return the module-level API key cache lock, creating it lazily."""
    return lazy_async_lock(_API_KEY_CACHE_LOCK_REF, API_KEY_LOCK_INIT_GUARD)


def get_api_keys_table() -> sa.Table:
    """Return the ``auth_api_keys`` SA ``Table``, creating it once if needed."""
    if API_KEYS_TABLE_REF[0] is None:
        meta = get_metadata()
        API_KEYS_TABLE_REF[0] = sa.Table(
            "auth_api_keys",
            meta,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("credential_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("user_id", sa.Integer, nullable=False, index=True),
            sa.Column("name", sa.String(255), nullable=True),
            sa.Column("scopes", sa.String(512), nullable=False, default=""),
            sa.Column("is_active", sa.Boolean, nullable=False, default=True),
            sa.Column("created_at", sa.DateTime, nullable=True),
            sa.Column("expires_at", sa.DateTime, nullable=True),
            extend_existing=True,
        )
    table = API_KEYS_TABLE_REF[0]
    if table is None:
        raise RuntimeError("API keys table initialization failed.")
    return table


async def ensure_api_keys_table() -> None:
    """Create the ``auth_api_keys`` table if it does not yet exist."""
    table = get_api_keys_table()
    await ensure_table(table, _API_KEYS_ENSURED, API_KEYS_ENSURE_LOCK)


def evict_api_key_cache_if_full(now: float) -> None:
    """Evict stale then oldest entries when the API key cache is at capacity.

    Must be called while holding the API key cache lock.
    """
    evict_cache_if_full(API_KEY_CACHE, API_KEY_CACHE_MAXSIZE, now, lambda v: v[2])


async def create_api_key_credential(
    key: str,
    secret: str,
    user_id: int,
    *,
    name: str | None = None,
    scopes: str = "",
    expires_at: datetime.datetime | None = None,
) -> AuthPayload:
    """Store a single API key credential (key + secret pair) in the database.

    The *key* and *secret* are joined with a ``.`` separator and hashed with
    SHA-256 before storage.  The raw values are never persisted.

    Args:
        key: The public key portion of the API key pair.
        secret: The secret portion of the API key pair.
        user_id: Primary key of the user that owns this credential.
        name: Optional human-readable label for the credential.
        scopes: Space-separated scope string (e.g. ``"read write"``).
        expires_at: Optional UTC datetime when the credential expires.

    Returns:
        A dict representation of the created row (excluding the raw values).
    """
    await ensure_api_keys_table()
    credential = f"{key}.{secret}"
    credential_hash = hash_token(credential)
    now_utc = timezone.now()
    table = get_api_keys_table()
    engine = await get_engine()

    async with engine.begin() as conn:
        stmt = (
            sa.insert(table)
            .values(
                credential_hash=credential_hash,
                user_id=user_id,
                name=name,
                scopes=scopes,
                is_active=True,
                created_at=now_utc,
                expires_at=expires_at,
            )
            .returning(
                table.c.id,
                table.c.credential_hash,
                table.c.user_id,
                table.c.name,
                table.c.scopes,
                table.c.is_active,
                table.c.created_at,
                table.c.expires_at,
            )
        )
        row = (await conn.execute(stmt)).one()

    record: AuthPayload = {
        "id": row.id,
        "credential_hash": row.credential_hash,
        "user_id": row.user_id,
        "name": row.name,
        "scopes": row.scopes,
        "is_active": row.is_active,
        "created_at": row.created_at,
        "expires_at": row.expires_at,
    }
    logger.debug("Created API key credential for user_id=%s", user_id)
    return record


async def create_api_key_pair(
    user_id: int,
    *,
    name: str | None = None,
    scopes: str = "",
    expires_at: datetime.datetime | None = None,
    store_reverse: bool = True,
) -> tuple[str, AuthPayload]:
    """Generate a new API key pair and store it in the database.

    An API key pair consists of a random *key* and *secret*, both 32-byte hex
    strings.  By default both ``key.secret`` and ``secret.key`` orders are
    stored so that the credential can be verified regardless of which half
    the client sends first.

    Args:
        user_id: Primary key of the user that owns this key pair.
        name: Optional human-readable label for the key pair.
        scopes: Space-separated scope string.
        expires_at: Optional UTC datetime when the key pair expires.
        store_reverse: If ``True`` (default), also store the reversed order
            so that ``secret.key`` is a valid credential too.

    Returns:
        A 2-tuple ``(raw_key_pair, record)`` where *raw_key_pair* is the
        ``key.secret`` string (returned exactly once) and *record* is the
        dict representation of the primary credential row.
    """
    await ensure_api_keys_table()
    key = secrets.token_hex(32)
    secret = secrets.token_hex(32)
    raw_key_pair = f"{key}.{secret}"

    record = await create_api_key_credential(
        key,
        secret,
        user_id,
        name=name,
        scopes=scopes,
        expires_at=expires_at,
    )

    if store_reverse:
        await create_api_key_credential(
            secret,
            key,
            user_id,
            name=name,
            scopes=scopes,
            expires_at=expires_at,
        )

    return raw_key_pair, record


async def reverse_api_key_credential(
    key: str,
    secret: str,
) -> str:
    """Return the hash of the reversed credential order ``secret.key``.

    This is a pure utility - it does **not** modify the database.  Callers
    can use the returned hash to look up the reversed row if needed.

    Args:
        key: The public key portion.
        secret: The secret portion.

    Returns:
        The SHA-256 hex-digest of ``secret.key``.
    """
    if not key or not secret:
        raise ValueError("Both key and secret must be non-empty strings.")
    reversed_credential = f"{secret}.{key}"
    return hash_token(reversed_credential)


async def revoke_api_key_pair(
    key: str,
    secret: str,
) -> None:
    """Revoke both credential orders (``key.secret`` and ``secret.key``).

    Marks both rows ``is_active = False`` in the database and evicts the
    corresponding entries from the in-process cache.

    Args:
        key: The public key portion of the API key pair.
        secret: The secret portion of the API key pair.
    """
    await ensure_api_keys_table()
    forward_hash = hash_token(f"{key}.{secret}")
    reverse_hash = hash_token(f"{secret}.{key}")
    table = get_api_keys_table()
    engine = await get_engine()

    async with engine.begin() as conn:
        await conn.execute(
            sa.update(table)
            .where(table.c.credential_hash.in_([forward_hash, reverse_hash]))
            .values(is_active=False)
        )

    lock = get_api_key_cache_lock()
    async with lock:
        API_KEY_CACHE.pop(forward_hash, None)
        API_KEY_CACHE.pop(reverse_hash, None)

    logger.debug(
        "Revoked API key pair (hash prefixes %s…, %s…)",
        forward_hash[:8],
        reverse_hash[:8],
    )


def clear_api_key_cache() -> None:
    """Clear the in-process API key cache.  Intended for tests and clean shutdown."""
    API_KEY_CACHE.clear()


class TokenAuthentication(BaseAuthentication):
    """Authenticate requests carrying an ``Authorization: Token <token>`` header.

    Resolution order:
    1. Parse the ``Authorization`` header; reject anything not starting with
       ``"Token "``.
    2. Hash the raw token and check the in-process TTL cache.
    3. On cache miss, query the ``auth_tokens`` table; validate ``is_active``
       and optional ``expires_at``.
    4. Fetch the associated user via :func:`get_user_cached`.
    5. Populate the cache and return ``(user, {"type": "token"})``.
    """

    async def authenticate(self, request: Request) -> tuple[Authenticable, AuthPayload] | None:
        auth_header: str | None = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Token "):
            return None

        raw = auth_header[6:]
        if not raw:
            return None

        key_hash = hash_token(raw)
        now_mono = time.monotonic()

        # Release the lock before async I/O to avoid blocking concurrent cache reads.
        cached_user_id: int | None = None
        lock = get_token_cache_lock()
        async with lock:
            cached = TOKEN_CACHE.get(key_hash)
            if cached is not None:
                uid, cache_expires = cached
                if now_mono < cache_expires:
                    cached_user_id = uid
                else:
                    del TOKEN_CACHE[key_hash]

        if cached_user_id is not None:
            user = await get_user_cached(cached_user_id)
            if user and getattr(user, "is_active", True):
                return user, {"type": "token"}

        # Cache miss requires a database round-trip.
        try:
            await ensure_auth_tokens_table()
            table = get_auth_tokens_table()
            engine = await get_engine()

            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        sa.select(
                            table.c.user_id,
                            table.c.is_active,
                            table.c.expires_at,
                        ).where(table.c.key_hash == key_hash)
                    )
                ).one_or_none()

            if row is None:
                logger.debug("Token not found in DB (hash prefix %s\u2026)", key_hash[:8])
                return None

            if not row.is_active:
                logger.debug("Token is inactive (hash prefix %s\u2026)", key_hash[:8])
                return None

            if row.expires_at is not None:
                now_utc = timezone.now()
                exp = row.expires_at
                # Compare naive-to-naive when the DB stores offset-naive datetimes.
                if hasattr(exp, "tzinfo") and exp.tzinfo is None and hasattr(now_utc, "tzinfo"):
                    now_compare = now_utc.replace(tzinfo=None)
                else:
                    now_compare = now_utc
                if now_compare > exp:
                    logger.debug("Token has expired (hash prefix %s\u2026)", key_hash[:8])
                    return None

            user_id: int = row.user_id
            user = await get_user_cached(user_id)
            if not user or not getattr(user, "is_active", True):
                return None

            async with lock:
                evict_token_cache_if_full(now_mono)
                TOKEN_CACHE[key_hash] = (user_id, now_mono + TOKEN_CACHE_TTL)

            return user, {"type": "token"}

        except (ValueError, KeyError, LookupError, RuntimeError) as exc:
            logger.warning("TokenAuthentication error: %s", exc)
            return None

    def authenticate_header(self, request: Request) -> str:
        return "Token"


# Reject event names outside the configured lifecycle hooks.
_OAUTH2_EVENT_NAMES: frozenset[str] = frozenset({"on_success", "on_fail", "on_error", "on_initial"})

_DOTTED_PATH_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)+$")


class OAuth2Authentication(BaseAuthentication):
    """OAuth2 authentication backend with configurable lifecycle events.

    Provides ``authenticate`` for Bearer-token-based OAuth2 flows and an
    event system driven by ``OAUTH2_EVENTS`` in settings. Supported event
    names: ``on_success``, ``on_fail``, ``on_error``, ``on_initial``.
    """

    async def authenticate(self, request: Request) -> tuple[Authenticable, AuthPayload] | None:
        """Validate an OAuth2 Bearer token from the ``Authorization`` header.

        Returns ``(user, {"type": "oauth2"})`` on success,
        ``None`` if the header is absent or the scheme is not ``Bearer``.
        Subclasses should override this method and call ``trigger_event``
        at the appropriate lifecycle points.
        """
        auth_header: str | None = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None

        token = auth_header[7:]
        if not token:
            return None

        try:
            payload = self.build_payload(token=token, request=request, authentication_type="oauth2")
            user_id = await self.resolve_oauth2_user(token)
            if user_id is None:
                await self.trigger_event("on_fail", payload)
                return None

            user = await get_user_cached(user_id)
            if not user or not getattr(user, "is_active", True):
                await self.trigger_event("on_fail", payload)
                return None

            payload = self.build_payload(
                token=token,
                request=request,
                authentication_type="oauth2",
                email=getattr(user, "email", ""),
                name=getattr(user, "username", ""),
                provider_user_id=str(user_id),
            )

            if await self.is_first_login(user):
                await self.trigger_event("on_initial", payload)

            await self.trigger_event("on_success", payload)
            return user, {"type": "oauth2"}

        except (ValueError, KeyError, LookupError, OSError) as exc:
            error_payload = self.build_payload(
                token=token, request=request, authentication_type="oauth2", error=str(exc)
            )
            await self.trigger_event("on_error", error_payload)
            logger.warning("OAuth2 authentication error: %s", exc)
            return None

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"

    def load_oauth2_events(self) -> dict[str, str]:
        """Return the ``OAUTH2_EVENTS`` mapping from settings.

        Returns an empty dict when the setting is absent, ensuring the event
        system degrades gracefully with no configuration required.
        """
        return dict(getattr(settings, "OAUTH2_EVENTS", {}))

    def resolve_event_handler(self, path: str) -> OAuth2EventHandler:
        """Import and return the callable at the given dotted *path*.

        Args:
            path: A fully-qualified dotted import path such as
                ``"myapp.events.oauth_success"``.

        Returns:
            The imported callable.

        Raises:
            ValueError: If *path* does not look like a valid dotted path.
            ImportError: If the module cannot be imported.
            AttributeError: If the attribute is absent from the module.
        """
        if not _DOTTED_PATH_RE.match(path):
            raise ValueError(
                f"Invalid event handler path {path!r}. "
                "Expected a fully-qualified dotted Python path "
                "(e.g. 'myapp.events.oauth_success')."
            )
        return cast("OAuth2EventHandler", import_string_uncached(path))

    async def trigger_event(self, event_name: str, payload: AuthPayload) -> None:
        """Trigger the named OAuth2 lifecycle event with *payload*.

        The call is completely safe: import errors and handler exceptions are
        both caught, logged, and swallowed so that authentication is never
        interrupted by a broken event handler.

        Args:
            event_name: One of ``on_success``, ``on_fail``, ``on_error``,
                ``on_initial``.
            payload: Arbitrary dict passed verbatim to the handler.
        """
        if event_name not in _OAUTH2_EVENT_NAMES:
            logger.debug("Unknown OAuth2 event name %r - skipping.", event_name)
            return

        events = self.load_oauth2_events()
        handler_path = events.get(event_name)
        if not handler_path:
            return

        try:
            handler = self.resolve_event_handler(handler_path)
        except (ImportError, AttributeError, ValueError) as exc:
            logger.error(
                "OAuth2 event %r: could not import handler %r - %s",
                event_name,
                handler_path,
                exc,
            )
            return

        try:
            result = handler(payload)
            if inspect.isawaitable(result):
                await result
        except (TypeError, ValueError, AttributeError, RuntimeError) as exc:
            logger.error(
                "OAuth2 event %r: handler %r raised %s - %s",
                event_name,
                handler_path,
                type(exc).__name__,
                exc,
            )

    def build_payload(
        self,
        *,
        token: str,
        request: object,
        authentication_type: str,
        provider: str = "",
        user_info: AuthPayload | None = None,
        email: str = "",
        name: str = "",
        provider_user_id: str = "",
        error: str = "",
    ) -> AuthPayload:
        """Assemble the standard event payload dict.

        The raw ``token`` is never included in the payload to prevent
        credential leakage through event handlers or log output.
        """
        return {
            "provider": provider,
            "user_info": user_info or {},
            "email": email,
            "name": name,
            "provider_user_id": provider_user_id,
            "request": request,
            "authentication_type": authentication_type,
            "error": error,
        }

    async def resolve_oauth2_user(self, token: str) -> int | str | None:
        """Decode the OAuth2 Bearer token and return the user ID, or ``None``.

        The default implementation attempts JWT decoding via the shared
        :func:`decode_access_token` helper.  Subclasses can override this
        to support provider-specific introspection.
        """
        try:
            jwt_payload = await decode_access_token_checked(token)
            user_id = jwt_payload.get("sub")
            return user_id if isinstance(user_id, int | str) else None
        except AuthenticationFailed, ValueError, KeyError, JWTError:
            return None

    async def is_first_login(self, user: Authenticable) -> bool:
        """Return ``True`` when *user* has never logged in before.

        Checks ``last_login`` on the user object.  Subclasses may override
        to query an external store.
        """
        return getattr(user, "last_login", None) is None
