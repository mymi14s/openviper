"""Database alias to backend instance mapping and lifecycle management."""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, ClassVar

from openviper.conf import settings
from openviper.db.backends.db_registry import get_database_backend_class
from openviper.db.exceptions import (
    DatabaseAliasNotFoundError,
)

if TYPE_CHECKING:
    from openviper.db.backends.database import DatabaseBackend

logger = logging.getLogger(__name__)

DEFAULT_ALIAS: str = "default"


class ConnectionManager:
    """Manage configured database aliases and backend instances.

    Loads ``DATABASES`` configuration, normalizes ``DATABASE_URL``
    into a single-alias config when ``DATABASES`` is absent, and
    instantiates one ``DatabaseBackend`` per alias.
    """

    def __init__(self) -> None:
        self.backends: dict[str, DatabaseBackend] = {}
        self.initialized: bool = False
        self._init_lock = threading.Lock()

    # Metadata keys inside DATABASES that are not alias configurations.
    _METADATA_KEYS: ClassVar[frozenset[str]] = frozenset({"ROUTERS", "ROUTING"})

    def configure(self, databases: Mapping[str, object] | None = None) -> None:
        """Load DATABASES config and instantiate backends.

        If *databases* is ``None`` or empty, falls back to
        ``DATABASE_URL`` from settings.
        """
        with self._init_lock:
            if self.initialized:
                return

            configured_databases = databases
            if configured_databases is None:
                configured_databases = getattr(settings, "DATABASES", {})

            if configured_databases:
                for alias, config in configured_databases.items():
                    if alias in self._METADATA_KEYS:
                        continue
                    if not isinstance(config, Mapping):
                        raise TypeError(
                            f"Database alias '{alias}' configuration must be a mapping."
                        )
                    self.setup_alias(alias, config)
            else:
                self.normalize_database_url()

            self.initialized = True

    def normalize_database_url(self) -> None:
        """Normalize DATABASE_URL into a single default alias config."""
        database_url = getattr(settings, "DATABASE_URL", "")
        if not database_url:
            return

        echo = getattr(settings, "DATABASE_ECHO", False)
        pool_size = getattr(settings, "DATABASE_POOL_SIZE", 5)
        max_overflow = getattr(settings, "DATABASE_MAX_OVERFLOW", 10)
        pool_recycle = getattr(settings, "DATABASE_POOL_RECYCLE", 3600)

        config: dict[str, object] = {
            "BACKEND": "openviper.db.backends.DefaultDatabaseBackend",
            "OPTIONS": {
                "URL": database_url,
                "ECHO": echo,
                "POOL_SIZE": pool_size,
                "MAX_OVERFLOW": max_overflow,
                "POOL_RECYCLE": pool_recycle,
            },
            "ROLE": "primary",
        }
        self.setup_alias(DEFAULT_ALIAS, config)

    def setup_alias(self, alias: str, config: Mapping[str, object]) -> None:
        """Instantiate and store a backend for the given alias."""
        backend_cls = get_database_backend_class(config)
        backend = backend_cls(alias, config)
        self.backends[alias] = backend
        logger.debug(
            "Database alias '%s' configured with backend '%s'.",
            alias,
            type(backend).__name__,
        )

    def get(self, alias: str | None = None) -> DatabaseBackend:
        """Return the backend for *alias*, defaulting to ``'default'``.

        Raises ``DatabaseAliasNotFoundError`` for unknown aliases.
        """
        self.ensure_initialized()
        resolved = alias if alias is not None else DEFAULT_ALIAS
        backend = self.backends.get(resolved)
        if backend is None:
            raise DatabaseAliasNotFoundError(
                f"Database alias '{resolved}' is not configured. "
                f"Available aliases: {list(self.backends)}."
            )
        return backend

    def all(self) -> Sequence[DatabaseBackend]:
        """Return all configured backend instances."""
        self.ensure_initialized()
        return list(self.backends.values())

    async def disconnect_all(self) -> None:
        """Dispose all backend engines and pooled connections."""
        for backend in self.backends.values():
            try:
                await backend.disconnect()
            except Exception:
                logger.debug(
                    "Error disconnecting backend '%s'.",
                    backend.alias,
                    exc_info=True,
                )
        self.backends.clear()
        self.initialized = False

    def ensure_initialized(self) -> None:
        """Lazy-initialize from settings if not yet configured."""
        if not self.initialized:
            self.configure()

    @property
    def aliases(self) -> list[str]:
        """Return all configured alias names."""
        self.ensure_initialized()
        return list(self.backends.keys())


connections = ConnectionManager()
