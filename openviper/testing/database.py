"""Database setup and isolation helpers for OpenViper pytest fixtures."""

import dataclasses
import os
import warnings
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import sqlalchemy as sa

from openviper.db.connection import (
    close_db,
    configure_db,
    get_engine,
    get_metadata,
    init_db,
    request_connection,
)
from openviper.db.connections import connections
from openviper.db.routing.context import reset_routing_context
from openviper.testing.settings import DatabaseIsolation, OpenViperTestingConfigError


def should_create_db() -> bool:
    """Return True when OPENVIPER_TEST_CREATE_DB is set in the environment."""
    return os.environ.get("OPENVIPER_TEST_CREATE_DB", "") == "1"


def should_reuse_db() -> bool:
    """Return True when OPENVIPER_TEST_REUSE_DB is set in the environment."""
    return os.environ.get("OPENVIPER_TEST_REUSE_DB", "") == "1"


async def configure_and_init_db(url: str, *, migrate: bool) -> None:
    """Configure the database engine and optionally run initial migrations."""
    assert_safe_database_url(url)
    await configure_db(url)
    if migrate and (not should_reuse_db() or should_create_db()):
        await init_db(drop_first=True)


async def reset_database_by_isolation(isolation: DatabaseIsolation) -> None:
    """Reset test data according to the isolation strategy."""
    if should_reuse_db():
        return
    if isolation in {"recreate", "in_memory"}:
        await init_db(drop_first=True)
    elif isolation == "truncate":
        await truncate_database()


@dataclasses.dataclass(frozen=True, slots=True)
class SessionDatabase:
    """Session-scoped database handle: migrate once, isolate per test."""

    __test__ = False

    url: str
    isolation: DatabaseIsolation

    async def setup(self) -> None:
        """Configure the engine and run migrations exactly once."""
        await configure_and_init_db(self.url, migrate=True)

    async def reset(self) -> None:
        """Clean test data between tests without re-running migrations."""
        effective_isolation = "recreate" if self.isolation == "transaction" else self.isolation
        await reset_database_by_isolation(effective_isolation)

    async def teardown(self) -> None:
        """Close the engine after the full session completes."""
        await close_db()


@dataclasses.dataclass(frozen=True, slots=True)
class TestDatabase:
    """Configured test database handle."""

    __test__ = False

    url: str
    isolation: DatabaseIsolation
    migrate: bool

    async def setup(self) -> None:
        await configure_and_init_db(self.url, migrate=self.migrate)

    async def reset(self) -> None:
        await reset_database_by_isolation(self.isolation)

    async def teardown(self) -> None:
        await close_db()


@asynccontextmanager
async def database_context(database: TestDatabase) -> AsyncIterator[TestDatabase]:
    """Configure a test database and clean it after use.

    Transaction isolation wraps the test in ``request_connection()`` for
    automatic rollback. Other modes run explicit cleanup after each test.
    """
    await database.setup()
    try:
        if database.isolation == "transaction":
            async with request_connection():
                yield database
        else:
            try:
                yield database
            finally:
                await database.reset()
    finally:
        await database.teardown()


@asynccontextmanager
async def session_database_context(database: SessionDatabase) -> AsyncIterator[SessionDatabase]:
    """Migrate once at session start, close connection at session end."""

    await database.setup()
    try:
        yield database
    finally:
        await database.teardown()


def resolve_test_database_url(database_url: str | None, isolation: DatabaseIsolation) -> str:
    """Resolve a test database URL from config values."""
    url = database_url or "sqlite+aiosqlite:///:memory:"
    if isolation == "in_memory":
        url = "sqlite+aiosqlite:///:memory:"
    return url


def build_session_database(
    database_url: str | None,
    isolation: DatabaseIsolation,
) -> SessionDatabase:
    """Create a session-scoped database descriptor from config values."""

    return SessionDatabase(
        url=resolve_test_database_url(database_url, isolation),
        isolation=isolation,
    )


def build_test_database(
    database_url: str | None,
    isolation: DatabaseIsolation,
    migrate: bool,
) -> TestDatabase:
    """Create a safe test database descriptor from config values."""

    return TestDatabase(
        url=resolve_test_database_url(database_url, isolation),
        isolation=isolation,
        migrate=migrate,
    )


async def truncate_database() -> None:
    """Delete rows from all registered tables without dropping metadata.

    Uses ``TRUNCATE ... CASCADE`` for PostgreSQL/MySQL. Falls back to
    per-table DELETE for SQLite and other dialects.
    """

    metadata = get_metadata()
    engine = await get_engine()
    dialect = str(engine.url)

    async with engine.begin() as connection:
        if "sqlite" in dialect:
            await connection.execute(sa.text("PRAGMA foreign_keys=OFF"))
            for table in reversed(metadata.sorted_tables):
                await connection.execute(table.delete())
            await connection.execute(sa.text("PRAGMA foreign_keys=ON"))
        elif "postgresql" in dialect or "mysql" in dialect:
            table_names = ", ".join(f'"{table.name}"' for table in reversed(metadata.sorted_tables))
            cascade = " CASCADE" if "postgresql" in dialect else ""
            await connection.execute(sa.text(f"TRUNCATE {table_names}{cascade}"))
        else:
            for table in reversed(metadata.sorted_tables):
                await connection.execute(table.delete())


async def migrate_database(drop_first: bool = False) -> None:
    """Create registered tables using OpenViper metadata."""

    await init_db(drop_first=drop_first)


def assert_safe_database_url(database_url: str) -> None:
    """Reject empty or production-looking database URLs."""

    parsed = urlparse(database_url)
    if not database_url.strip():
        raise OpenViperTestingConfigError("Test database URL must not be empty.")
    if ":memory:" in database_url:
        return

    database_name = (parsed.path or "").rsplit("/", 1)[-1].lower()
    hostname = (parsed.hostname or "").lower()
    unsafe_names = {"prod", "production", "main", "live"}
    if database_name in unsafe_names or hostname in {"prod", "production", "live"}:
        raise OpenViperTestingConfigError(
            "Refusing to use a production-looking database URL for tests."
        )
    if "sqlite" in parsed.scheme:
        if parsed.path and database_name and "test" not in database_name:
            warnings.warn(
                f"SQLite file database {database_name!r} does not contain 'test' in its name."
                " Ensure this is not a production database.",
                stacklevel=2,
            )
    elif database_name and "test" not in database_name:
        raise OpenViperTestingConfigError(
            f"Non-SQLite test database name {database_name!r} must contain 'test'."
        )


@dataclasses.dataclass(frozen=True, slots=True)
class MultiDatabaseConfig:
    """Configuration for multi-database test setups."""

    __test__ = False

    databases: dict[str, dict[str, object]]

    def primary(self) -> dict[str, object]:
        """Return the primary (default) database config."""
        return self.databases.get("default", {})

    def replicas(self) -> dict[str, dict[str, object]]:
        """Return all replica database configs."""
        return {
            alias: config
            for alias, config in self.databases.items()
            if config.get("ROLE") == "replica"
        }


def build_multi_database_config(
    primary_url: str,
    replica_urls: list[str] | None = None,
) -> MultiDatabaseConfig:
    """Build a multi-database test configuration from primary and replica URLs."""
    databases: dict[str, dict[str, object]] = {
        "default": {
            "URL": primary_url,
            "ROLE": "primary",
        },
    }
    for i, url in enumerate(replica_urls or [], start=1):
        alias = f"replica_{i}" if i > 1 else "replica"
        databases[alias] = {
            "URL": url,
            "ROLE": "replica",
            "READ_ONLY": True,
        }
    return MultiDatabaseConfig(databases=databases)


async def setup_test_databases(config: MultiDatabaseConfig) -> None:
    """Configure and initialize all test database aliases."""

    connections.configure(databases=config.databases)
    for alias in connections.aliases:
        backend = connections.get(alias)
        await backend.init_db(drop_first=True)


async def teardown_test_databases() -> None:
    """Disconnect all test database backends and reset routing state."""

    await connections.disconnect_all()
    reset_routing_context()


class DatabaseAliasTracker:
    """Track which database alias was used for read/write operations."""

    __test__ = False

    def __init__(self) -> None:
        self.reads: list[tuple[str, type]] = []
        self.writes: list[tuple[str, type]] = []

    def record_read(self, alias: str, model_class: type) -> None:
        self.reads.append((alias, model_class))

    def record_write(self, alias: str, model_class: type) -> None:
        self.writes.append((alias, model_class))

    def clear(self) -> None:
        self.reads.clear()
        self.writes.clear()

    def assert_db_used(
        self,
        alias: str,
        *,
        for_read: bool = False,
        for_write: bool = False,
    ) -> None:
        """Assert that *alias* was used for a read or write operation."""
        if for_read:
            read_aliases = [a for a, _ in self.reads]
            assert alias in read_aliases, f"Expected read on '{alias}', got {read_aliases}"
        if for_write:
            write_aliases = [a for a, _ in self.writes]
            assert alias in write_aliases, f"Expected write on '{alias}', got {write_aliases}"
        return
