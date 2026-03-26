"""Session store for OpenViper.

Provides an abstract base class for session storage and a default
database-backed implementation with cache-through support.
"""

from __future__ import annotations

import abc
import datetime
import json
import logging
from typing import Any

import sqlalchemy as sa

from openviper.auth.session.utils import (
    _ensure_table,
    _get_session_table,
    _is_valid_session_key,
    generate_session_key,
)
from openviper.auth.user import get_user_by_id
from openviper.cache import get_cache
from openviper.conf import settings
from openviper.db.connection import get_engine
from openviper.utils import timezone
from openviper.utils.importlib import import_string

logger = logging.getLogger("openviper.auth.session")

_SESSION_CACHE_PREFIX = "session:"
_SESSION_USER_CACHE_PREFIX = "session_user:"


def _get_session_ttl_seconds() -> int:
    """Return session cache TTL in seconds derived from settings."""
    timeout = getattr(settings, "SESSION_TIMEOUT", datetime.timedelta(hours=1))
    if isinstance(timeout, datetime.timedelta):
        return int(timeout.total_seconds())
    return int(timeout)


class Session:
    """A container for session data that tracks changes."""

    def __init__(
        self,
        key: str,
        data: dict[str, Any] | None = None,
        store: BaseSessionStore | None = None,
    ) -> None:
        self.key = key
        self._data = data or {}
        self._store = store
        self._is_new = data is None
        self._is_modified = False

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._is_modified = True

    def __delitem__(self, key: str) -> None:
        del self._data[key]
        self._is_modified = True

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self[key] = value

    def update(self, data: dict[str, Any]) -> None:
        self._data.update(data)
        self._is_modified = True

    def clear(self) -> None:
        self._data.clear()
        self._is_modified = True

    @property
    def is_empty(self) -> bool:
        return not self._data

    async def save(self) -> None:
        """Persist the session data if it has changed."""
        if self._is_modified and self._store:
            await self._store.save(self.key, self._data)
            self._is_modified = False

    def __repr__(self) -> str:
        return f"<Session key={self.key!r} modified={self._is_modified}>"


class BaseSessionStore(abc.ABC):
    """Abstract base class for all session storage backends."""

    @abc.abstractmethod
    async def create(self, user_id: Any, data: dict[str, Any] | None = None) -> Session:
        """Create a new session and return a Session object."""
        pass

    @abc.abstractmethod
    async def load(self, session_key: str) -> Session | None:
        """Load session data and return a Session object."""
        pass

    @abc.abstractmethod
    async def save(
        self, session_key: str, data: dict[str, Any], expiry: datetime.datetime | None = None
    ) -> None:
        """Save session data."""
        pass

    @abc.abstractmethod
    async def delete(self, session_key: str) -> None:
        """Delete a session."""
        pass

    @abc.abstractmethod
    async def get_user(self, session_key: str) -> Any | None:
        """Retrieve the user associated with this session."""
        pass

    def generate_key(self) -> str:
        """Generate a random session key."""
        return generate_session_key()


class DatabaseSessionStore(BaseSessionStore):
    """SQLAlchemy-backed session store with cache-through support."""

    async def create(self, user_id: Any, data: dict[str, Any] | None = None) -> Session:
        await _ensure_table()
        table = _get_session_table()
        key = self.generate_key()

        timeout = getattr(settings, "SESSION_TIMEOUT", datetime.timedelta(hours=1))
        if not isinstance(timeout, datetime.timedelta):
            timeout = datetime.timedelta(seconds=int(timeout))

        expires = timezone.now() + timeout
        session_data = data or {}
        payload = json.dumps(session_data)

        engine = await get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                sa.insert(table).values(
                    session_key=key,
                    user_id=str(user_id),
                    data=payload,
                    expires_at=expires,
                    created_at=timezone.now(),
                )
            )

        cache = get_cache()
        ttl = _get_session_ttl_seconds()
        await cache.set(f"{_SESSION_CACHE_PREFIX}{key}", session_data, ttl=ttl)
        await cache.set(f"{_SESSION_USER_CACHE_PREFIX}{key}", str(user_id), ttl=ttl)

        return Session(key, session_data, self)

    async def load(self, session_key: str) -> Session | None:
        if not _is_valid_session_key(session_key):
            return None

        cache = get_cache()
        cache_key = f"{_SESSION_CACHE_PREFIX}{session_key}"
        cached = await cache.get(cache_key)
        if cached is not None:
            return Session(session_key, cached, self)

        await _ensure_table()
        table = _get_session_table()
        engine = await get_engine()

        async with engine.connect() as conn:
            result = await conn.execute(
                sa.select(table).where(
                    sa.and_(
                        table.c.session_key == session_key,
                        table.c.expires_at > timezone.now(),
                    )
                )
            )
            row = result.fetchone()

        if row is None:
            return None

        try:
            data = json.loads(row.data)
        except json.JSONDecodeError:
            data = {}

        ttl = _get_session_ttl_seconds()
        await cache.set(cache_key, data, ttl=ttl)

        return Session(session_key, data, self)

    async def save(
        self, session_key: str, data: dict[str, Any], expiry: datetime.datetime | None = None
    ) -> None:
        await _ensure_table()
        table = _get_session_table()
        engine = await get_engine()

        values: dict[str, Any] = {"data": json.dumps(data)}
        if expiry:
            values["expires_at"] = expiry

        async with engine.begin() as conn:
            await conn.execute(
                sa.update(table).where(table.c.session_key == session_key).values(**values)
            )

        cache = get_cache()
        ttl = _get_session_ttl_seconds()
        await cache.set(f"{_SESSION_CACHE_PREFIX}{session_key}", data, ttl=ttl)

    async def delete(self, session_key: str) -> None:
        if not _is_valid_session_key(session_key):
            return
        await _ensure_table()
        table = _get_session_table()
        engine = await get_engine()
        async with engine.begin() as conn:
            await conn.execute(sa.delete(table).where(table.c.session_key == session_key))

        cache = get_cache()
        await cache.delete(f"{_SESSION_CACHE_PREFIX}{session_key}")
        await cache.delete(f"{_SESSION_USER_CACHE_PREFIX}{session_key}")

    async def get_user(self, session_key: str) -> Any | None:
        if not _is_valid_session_key(session_key):
            logger.debug("get_user: Invalid session key format")
            return None

        cache = get_cache()
        user_cache_key = f"{_SESSION_USER_CACHE_PREFIX}{session_key}"
        cached_user_id = await cache.get(user_cache_key)
        if cached_user_id is not None:
            user = await get_user_by_id(cached_user_id)
            if user:
                return user

        await _ensure_table()
        table = _get_session_table()
        engine = await get_engine()

        async with engine.connect() as conn:
            result = await conn.execute(
                sa.select(table.c.user_id, table.c.expires_at).where(
                    table.c.session_key == session_key
                )
            )
            row = result.fetchone()

        if row is None:
            logger.debug("get_user: No session found for key")
            return None

        if row.expires_at < timezone.now():
            logger.debug("get_user: Session expired at %s", row.expires_at)
            return None

        if row.user_id is None:
            logger.debug("get_user: Session has no user_id")
            return None

        ttl = _get_session_ttl_seconds()
        await cache.set(user_cache_key, row.user_id, ttl=ttl)

        user = await get_user_by_id(row.user_id)
        logger.debug("get_user: Identified user %s", user)
        return user

    async def rotate(
        self, old_session_key: str, user_id: Any, data: dict[str, Any] | None = None
    ) -> Session:
        """Invalidate old session and create a new one."""
        await self.delete(old_session_key)
        return await self.create(user_id, data)


# ---------------------------------------------------------------------------
# Store factory
# ---------------------------------------------------------------------------

_STORE_INSTANCE: BaseSessionStore | None = None


def get_session_store() -> BaseSessionStore:
    """Return the configured session store singleton.

    Reads ``settings.SESSION_STORE`` and returns the appropriate backend.
    """
    global _STORE_INSTANCE
    if _STORE_INSTANCE is not None:
        return _STORE_INSTANCE

    backend = getattr(settings, "SESSION_STORE", "database")
    if backend == "database":
        _STORE_INSTANCE = DatabaseSessionStore()
    elif "." in backend:
        store_cls = import_string(backend)
        _STORE_INSTANCE = store_cls()
    else:
        logger.warning("Unknown SESSION_STORE %r, falling back to database.", backend)
        _STORE_INSTANCE = DatabaseSessionStore()

    return _STORE_INSTANCE


def _reset_store_instance() -> None:
    """Reset the store singleton (for testing only)."""
    global _STORE_INSTANCE
    _STORE_INSTANCE = None
