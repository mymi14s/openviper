"""Session store for OpenViper.

Provides an abstract base class for session storage and a default
database-backed implementation with cache-through support.
"""

from __future__ import annotations

import abc
import datetime
import json
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

import sqlalchemy as sa

from openviper.auth.constants import SESSION_CACHE_PREFIX, SESSION_USER_CACHE_PREFIX
from openviper.auth.session.utils import (
    ensure_session_table,
    generate_session_key,
    get_session_table,
    is_valid_session_key,
)
from openviper.auth.user import get_user_by_id
from openviper.cache import get_cache
from openviper.conf import settings
from openviper.db.connection import get_engine
from openviper.utils import timezone
from openviper.utils.importlib import import_string

if TYPE_CHECKING:
    from openviper.auth.types import Authenticable, AuthPayload

logger = logging.getLogger("openviper.auth.session")


def get_session_ttl_seconds() -> int:
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
        data: AuthPayload | None = None,
        store: BaseSessionStore | None = None,
    ) -> None:
        self.key = key
        self._data = data or {}
        self._store = store
        self._is_new = data is None
        self._is_modified = False

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def __setitem__(self, key: str, value: object) -> None:
        self._data[key] = value
        self._is_modified = True

    def __delitem__(self, key: str) -> None:
        del self._data[key]
        self._is_modified = True

    def get(self, key: str, default: object = None) -> object:
        return self._data.get(key, default)

    def set(self, key: str, value: object) -> None:
        self[key] = value

    def update(self, data: AuthPayload) -> None:
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
    async def create(self, user_id: int | str, data: Mapping[str, object] | None = None) -> Session:
        """Create a new session and return a Session object."""
        pass

    @abc.abstractmethod
    async def load(self, session_key: str) -> Session | None:
        """Load session data and return a Session object."""
        pass

    @abc.abstractmethod
    async def save(
        self,
        session_key: str,
        data: Mapping[str, object],
        expiry: datetime.datetime | None = None,
    ) -> None:
        """Save session data."""
        pass

    @abc.abstractmethod
    async def delete(self, session_key: str) -> None:
        """Delete a session."""
        pass

    @abc.abstractmethod
    async def delete_user_sessions(self, user_id: int | str) -> None:
        """Delete all sessions belonging to *user_id*."""
        pass

    @abc.abstractmethod
    async def get_user(self, session_key: str) -> Authenticable | None:
        """Retrieve the user associated with this session."""
        pass

    def generate_key(self) -> str:
        """Generate a random session key."""
        return generate_session_key()


class DatabaseSessionStore(BaseSessionStore):
    """SQLAlchemy-backed session store with cache-through support."""

    async def create(self, user_id: int | str, data: Mapping[str, object] | None = None) -> Session:
        await ensure_session_table()
        table = get_session_table()
        key = self.generate_key()

        timeout = getattr(settings, "SESSION_TIMEOUT", datetime.timedelta(hours=1))
        if not isinstance(timeout, datetime.timedelta):
            timeout = datetime.timedelta(seconds=int(timeout))

        expires = timezone.now() + timeout
        session_data: AuthPayload = dict(data or {})
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
        ttl = get_session_ttl_seconds()
        await cache.set(f"{SESSION_CACHE_PREFIX}{key}", session_data, ttl=ttl)
        await cache.set(f"{SESSION_USER_CACHE_PREFIX}{key}", str(user_id), ttl=ttl)

        return Session(key, session_data, self)

    async def load(self, session_key: str) -> Session | None:
        if not is_valid_session_key(session_key):
            return None

        cache = get_cache()
        cache_key = f"{SESSION_CACHE_PREFIX}{session_key}"
        cached = await cache.get(cache_key)
        if cached is not None:
            return Session(session_key, cast("AuthPayload", cached), self)

        await ensure_session_table()
        table = get_session_table()
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
            data = cast("AuthPayload", json.loads(row.data))
        except json.JSONDecodeError:
            data = {}

        ttl = get_session_ttl_seconds()
        await cache.set(cache_key, data, ttl=ttl)

        return Session(session_key, data, self)

    async def save(
        self,
        session_key: str,
        data: Mapping[str, object],
        expiry: datetime.datetime | None = None,
    ) -> None:
        await ensure_session_table()
        table = get_session_table()
        engine = await get_engine()

        values: AuthPayload = {"data": json.dumps(dict(data))}
        if expiry:
            values["expires_at"] = expiry

        async with engine.begin() as conn:
            await conn.execute(
                sa.update(table).where(table.c.session_key == session_key).values(**values)
            )

        cache = get_cache()
        ttl = get_session_ttl_seconds()
        await cache.set(f"{SESSION_CACHE_PREFIX}{session_key}", data, ttl=ttl)

    async def delete(self, session_key: str) -> None:
        if not is_valid_session_key(session_key):
            return
        await ensure_session_table()
        table = get_session_table()
        engine = await get_engine()
        async with engine.begin() as conn:
            await conn.execute(sa.delete(table).where(table.c.session_key == session_key))

        cache = get_cache()
        await cache.delete(f"{SESSION_CACHE_PREFIX}{session_key}")
        await cache.delete(f"{SESSION_USER_CACHE_PREFIX}{session_key}")

    async def delete_user_sessions(self, user_id: int | str) -> None:
        if not user_id:
            return
        await ensure_session_table()
        table = get_session_table()
        engine = await get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                sa.select(table.c.session_key).where(table.c.user_id == str(user_id))
            )
            keys = [row[0] for row in result.all()]
            if keys:
                await conn.execute(sa.delete(table).where(table.c.user_id == str(user_id)))

        cache = get_cache()
        for key in keys:
            await cache.delete(f"{SESSION_CACHE_PREFIX}{key}")
            await cache.delete(f"{SESSION_USER_CACHE_PREFIX}{key}")

    async def get_user(self, session_key: str) -> Authenticable | None:
        if not is_valid_session_key(session_key):
            logger.debug("get_user: Invalid session key format")
            return None

        cache = get_cache()
        user_cache_key = f"{SESSION_USER_CACHE_PREFIX}{session_key}"
        cached_user_id = await cache.get(user_cache_key)
        if cached_user_id is not None and await self.session_exists(session_key):
            user = await get_user_by_id(cached_user_id)
            if user:
                return user

        await ensure_session_table()
        table = get_session_table()
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
            await cache.delete(user_cache_key)
            await cache.delete(f"{SESSION_CACHE_PREFIX}{session_key}")
            return None

        expires_at = row.expires_at
        if timezone.is_naive(expires_at) and settings.USE_TZ:
            expires_at = expires_at.replace(tzinfo=datetime.UTC)

        if expires_at < timezone.now():
            logger.debug("get_user: Session expired at %s", expires_at)
            await cache.delete(user_cache_key)
            await cache.delete(f"{SESSION_CACHE_PREFIX}{session_key}")
            return None

        if row.user_id is None:
            logger.debug("get_user: Session has no user_id")
            return None

        ttl = get_session_ttl_seconds()
        await cache.set(user_cache_key, row.user_id, ttl=ttl)

        user = await get_user_by_id(row.user_id)
        logger.debug("get_user: Identified user %s", user)
        return user

    async def session_exists(self, session_key: str) -> bool:
        """Verify a session record exists and is valid in the database."""
        if not is_valid_session_key(session_key):
            return False
        await ensure_session_table()
        table = get_session_table()
        engine = await get_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                sa.select(table.c.session_key).where(
                    sa.and_(
                        table.c.session_key == session_key,
                        table.c.expires_at > timezone.now(),
                    )
                )
            )
            return result.fetchone() is not None

    async def rotate(
        self,
        old_session_key: str,
        user_id: int | str,
        data: Mapping[str, object] | None = None,
    ) -> Session:
        """Invalidate old session and create a new one.

        Deletes the old session before creating the new one so that both
        sessions are never simultaneously valid, preventing a concurrent
        request from successfully replaying the old session key during the
        rotation window.
        """
        await self.delete(old_session_key)
        return await self.create(user_id, data)


_STORE_INSTANCE_REF: list[BaseSessionStore | None] = [None]


def get_session_store() -> BaseSessionStore:
    """Return the configured session store singleton.

    Reads ``settings.SESSION_STORE`` and returns the appropriate backend.
    """
    if _STORE_INSTANCE_REF[0] is not None:
        return _STORE_INSTANCE_REF[0]

    backend = getattr(settings, "SESSION_STORE", "database")
    if backend == "database":
        _STORE_INSTANCE_REF[0] = DatabaseSessionStore()
    elif "." in backend:
        store_cls = import_string(backend)
        _STORE_INSTANCE_REF[0] = cast("BaseSessionStore", store_cls())
    else:
        logger.warning("Unknown SESSION_STORE %r, falling back to database.", backend)
        _STORE_INSTANCE_REF[0] = DatabaseSessionStore()

    store = _STORE_INSTANCE_REF[0]
    if store is None:
        raise RuntimeError("Session store initialization failed.")
    return store


def reset_store_instance() -> None:
    """Reset the store singleton (for testing only)."""
    _STORE_INSTANCE_REF[0] = None
