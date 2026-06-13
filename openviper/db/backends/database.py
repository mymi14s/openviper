"""Database backend base class and component interfaces.

``DatabaseBackend`` controls the core SQL database layer - engine
creation, connections, transactions, execution, features, operations,
introspection, and test database creation.

``VirtualBackend`` (in ``base.py``) controls per-model custom data
sources (REST APIs, in-memory stores, etc.).  If
``model._meta.virtual`` is true, use ``VirtualBackend`` routing, not
``DatabaseBackend`` routing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from openviper.db.backends.client import DatabaseClient
from openviper.db.backends.creation import DatabaseCreation
from openviper.db.backends.execution import DatabaseExecution
from openviper.db.backends.features import DatabaseFeatures
from openviper.db.backends.introspection import DatabaseIntrospection
from openviper.db.backends.operations import DatabaseOperations
from openviper.db.shared_metadata import metadata


def get_shared_metadata() -> sa.MetaData:
    """Return shared SQLAlchemy metadata."""
    return metadata


class DatabaseBackend(ABC):
    """Extensible database backend wrapping OpenViper's SQLAlchemy integration.

    A ``DatabaseBackend`` controls how a configured SQL database alias
    creates engines, connections, transactions, and executes statements.
    It also exposes feature flags, operations, execution hooks,
    introspection, test database creation, and optional client helpers.

    Subclass to add instrumentation, retry logic, tracing, custom
    connection pool options, or dialect-specific behaviour.
    """

    vendor: str = "unknown"
    display_name: str = "Unknown Database"

    def __init__(self, alias: str, config: Mapping[str, object]) -> None:
        self.alias = alias
        self.config = dict(config)
        self.operations = self.create_operations()
        self.features = self.create_features()
        self.execution = self.create_execution()
        self.introspection = self.create_introspection()
        self.creation = self.create_creation()
        self.client = self.create_client()

    def create_features(self) -> DatabaseFeatures:
        """Return a ``DatabaseFeatures`` instance for this backend."""
        return DatabaseFeatures()

    def create_operations(self) -> DatabaseOperations:
        """Return a ``DatabaseOperations`` instance for this backend."""
        return DatabaseOperations()

    def create_execution(self) -> DatabaseExecution:
        """Return a ``DatabaseExecution`` instance for this backend."""
        return DatabaseExecution()

    def create_introspection(self) -> DatabaseIntrospection:
        """Return a ``DatabaseIntrospection`` instance for this backend."""
        return DatabaseIntrospection()

    def create_creation(self) -> DatabaseCreation:
        """Return a ``DatabaseCreation`` instance for this backend."""
        return DatabaseCreation(backend=self)

    def create_client(self) -> DatabaseClient:
        """Return a ``DatabaseClient`` instance for this backend."""
        return DatabaseClient(backend=self)

    @abstractmethod
    async def create_engine(self) -> AsyncEngine:
        """Create and return the async SQLAlchemy engine for this alias."""

    @abstractmethod
    async def connect(self) -> AsyncConnection:
        """Return an async database connection for this alias."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Dispose backend resources (engine, pool connections)."""

    @abstractmethod
    async def execute(
        self,
        statement: sa.Executable,
        parameters: Mapping[str, object] | None = None,
    ) -> object:
        """Execute a SQLAlchemy statement through the execution hooks."""

    @abstractmethod
    def transaction(self, using: str | None = None) -> AsyncGenerator[AsyncConnection]:
        """Return a transaction context manager.

        *using* is the database alias to pin the transaction to.
        When ``None``, the current alias (from context or default)
        is used.
        """

    def get_metadata(self) -> sa.MetaData:
        """Return the shared SQLAlchemy metadata for this backend.

        Default returns the module-level metadata from
        ``openviper.db.connection``.
        """
        return get_shared_metadata()

    @property
    def url(self) -> str:
        """Return the configured database URL for this alias.

        Resolution order:
          1. ``OPTIONS.URL`` (nested config format)
          2. ``URL`` directly in config (flat format)
        """
        options = self.config.get("OPTIONS")
        if isinstance(options, Mapping):
            value = options.get("URL")
            if isinstance(value, str) and value:
                return value
        value = self.config.get("URL", "")
        return value if isinstance(value, str) else ""

    @property
    def is_read_only(self) -> bool:
        """Return whether this alias is configured as read-only.

        Resolution order:
          1. ``OPTIONS.READ_ONLY`` (nested config format)
          2. ``READ_ONLY`` directly in config (flat format)
        """
        options = self.config.get("OPTIONS")
        if isinstance(options, Mapping) and "READ_ONLY" in options:
            return bool(options["READ_ONLY"])
        return bool(self.config.get("READ_ONLY", False))

    @property
    def role(self) -> str:
        """Return the configured role (``primary`` or ``replica``).

        Resolution order:
          1. ``OPTIONS.ROLE`` (nested config format)
          2. ``ROLE`` directly in config (flat format)
        """
        options = self.config.get("OPTIONS")
        if isinstance(options, Mapping):
            value = options.get("ROLE")
            if isinstance(value, str):
                return value
        value = self.config.get("ROLE", "primary")
        return value if isinstance(value, str) else "primary"

    def get_option(self, key: str, default: object = None) -> object:
        """Resolve a config key from OPTIONS first, then flat config."""
        options = self.config.get("OPTIONS")
        if isinstance(options, Mapping) and key in options:
            return options[key]
        return self.config.get(key, default)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(alias={self.alias!r}, vendor={self.vendor!r})"
