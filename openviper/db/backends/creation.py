"""Test database creation and destruction for backend alias."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from openviper.db.backends.database import DatabaseBackend

logger = logging.getLogger(__name__)


class DatabaseCreation:
    """Creates, destroys, and clones test databases for a configured alias.

    Used by OpenViper TestKit, pytest multi-database fixtures, and
    test database isolation.
    """

    def __init__(self, backend: DatabaseBackend) -> None:
        self.backend = backend

    async def create_test_database(self, engine: AsyncEngine) -> None:
        """Create all tables in the test database.

        Uses the shared metadata to create the schema.  For
        SQLite :memory: databases this is a no-op because the
        engine already points at a fresh in-memory database.
        """
        async with engine.begin() as conn:
            await conn.run_sync(self.backend.get_metadata().create_all)
        logger.info("Test database created for alias '%s'.", self.backend.alias)

    async def destroy_test_database(self, engine: AsyncEngine) -> None:
        """Drop all tables in the test database.

        For SQLite :memory: databases this is a no-op because the
        data disappears when the engine is disposed.
        """
        async with engine.begin() as conn:
            await conn.run_sync(self.backend.get_metadata().drop_all)
        logger.info("Test database destroyed for alias '%s'.", self.backend.alias)

    async def clone_test_database(
        self,
        source_engine: AsyncEngine,
        target_engine: AsyncEngine,
    ) -> None:
        """Clone schema from *source_engine* into *target_engine*.

        Default implementation creates the same metadata on the
        target.  Backends that support faster cloning (e.g.
        ``CREATE DATABASE ... TEMPLATE``) should override this.
        """
        metadata = self.backend.get_metadata()
        async with target_engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
        logger.info(
            "Test database cloned for alias '%s'.",
            self.backend.alias,
        )
