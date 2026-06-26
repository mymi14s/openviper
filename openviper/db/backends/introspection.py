"""Database schema introspection for backend alias."""

from __future__ import annotations

import warnings as _warnings
from typing import TYPE_CHECKING, Any, cast

import sqlalchemy as sa

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection


class DatabaseIntrospection:
    """Reads schema information from a configured database alias.

    Used by migrations, inspect commands, admin diagnostics, and
    testing to discover existing tables, columns, indexes, and
    constraints.
    """

    async def get_table_names(self, connection: AsyncConnection) -> list[str]:
        """Return all user table names in the current schema."""
        result = await connection.run_sync(
            lambda sync_conn: sa.inspect(sync_conn).get_table_names(),
        )
        return list(result)

    async def get_columns(
        self,
        connection: AsyncConnection,
        table_name: str,
    ) -> list[dict[str, Any]]:
        """Return column metadata dicts for *table_name*.

        Unrecognized column types (e.g. PostGIS geometry) are tolerated -
        the type key in each dict will be a generic ``sa.types.NullType``
        instead of a specific SQLAlchemy type.
        """

        def get_columns_sync(sync_conn: object) -> list[dict[str, Any]]:
            with _warnings.catch_warnings():
                _warnings.filterwarnings("ignore", message="Did not recognize type")
                inspector = sa.inspect(sync_conn)
                return (
                    cast("list[dict[str, Any]]", inspector.get_columns(table_name))
                    if inspector is not None
                    else []
                )

        result = await connection.run_sync(get_columns_sync)
        return cast("list[dict[str, Any]]", result)

    async def get_indexes(
        self,
        connection: AsyncConnection,
        table_name: str,
    ) -> list[dict[str, Any]]:
        """Return index metadata dicts for *table_name*."""
        result = await connection.run_sync(
            lambda sync_conn: sa.inspect(sync_conn).get_indexes(table_name),
        )
        return cast("list[dict[str, Any]]", result)

    async def get_constraints(
        self,
        connection: AsyncConnection,
        table_name: str,
    ) -> list[dict[str, Any]]:
        """Return constraint metadata dicts for *table_name*."""
        result = await connection.run_sync(
            lambda sync_conn: sa.inspect(sync_conn).get_unique_constraints(table_name),
        )
        return cast("list[dict[str, Any]]", result)

    async def get_foreign_keys(
        self,
        connection: AsyncConnection,
        table_name: str,
    ) -> list[dict[str, Any]]:
        """Return foreign key metadata dicts for *table_name*."""
        result = await connection.run_sync(
            lambda sync_conn: sa.inspect(sync_conn).get_foreign_keys(table_name),
        )
        return cast("list[dict[str, Any]]", result)
