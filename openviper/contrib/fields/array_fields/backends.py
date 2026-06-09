"""Backend adapters for array field database columns.

Each backend maps ArrayField to SQL DDL, serialises list values for
writes, and deserialises raw driver values to Python lists.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from openviper.conf import settings
from openviper.db import connection as db_connection
from openviper.db.utils import get_default_database_url

if TYPE_CHECKING:
    from openviper.contrib.fields.array_fields.base import ArrayField


def is_postgresql() -> bool:
    """Return True if the configured database engine targets PostgreSQL."""
    try:
        if db_connection._engine is not None:
            url = str(db_connection._engine.url)
            return "postgresql" in url or "postgres" in url
    except AttributeError, TypeError:
        pass
    try:
        url = get_default_database_url(settings)
        return "postgresql" in url or "postgres" in url
    except AttributeError, TypeError:
        pass
    return False


class BaseArrayBackend:
    """Abstract base for array field database backends."""

    dialect: str = "generic"

    def column_ddl(self, field: ArrayField) -> str:
        """Return SQL column type string for DDL generation."""
        raise NotImplementedError

    def to_db(self, value: list[Any]) -> Any:
        """Serialise a Python list for database insertion."""
        raise NotImplementedError

    def get_sa_type(self, field: ArrayField) -> sa.types.TypeEngine[Any]:
        """Return the SQLAlchemy type for column creation."""
        raise NotImplementedError


class PostgresArrayBackend(BaseArrayBackend):
    """PostgreSQL ARRAY backend using native array types."""

    dialect = "postgresql"

    def column_ddl(self, field: ArrayField) -> str:
        base_type = field.base_column_type
        return f"{base_type}[]"

    def to_db(self, value: list[Any]) -> list[Any]:
        return value

    def get_sa_type(self, field: ArrayField) -> sa.types.TypeEngine[Any]:
        base_type = field.base_column_type.upper()

        type_map: dict[str, sa.types.TypeEngine[Any]] = {
            "INTEGER": sa.Integer(),
            "BIGINT": sa.BigInteger(),
            "SMALLINT": sa.SmallInteger(),
            "REAL": sa.Float(),
            "TEXT": sa.Text(),
            "VARCHAR": sa.String(),
            "BOOLEAN": sa.Boolean(),
            "DATE": sa.Date(),
            "TIMESTAMP": sa.DateTime(),
        }

        inner = type_map.get(base_type, sa.Text())
        return sa.ARRAY(inner)


class FallbackJsonBackend(BaseArrayBackend):
    """Fallback backend storing arrays as JSON text on non-PostgreSQL databases."""

    dialect = "generic"

    def column_ddl(self, field: ArrayField) -> str:
        return "TEXT"

    def to_db(self, value: list[Any]) -> str:
        return json.dumps(value)

    def get_sa_type(self, field: ArrayField) -> sa.types.TypeEngine[Any]:
        return sa.Text()


_backend: BaseArrayBackend | None = None


def get_backend() -> BaseArrayBackend:
    """Return the appropriate array backend based on the configured database."""
    global _backend
    if _backend is not None:
        return _backend

    _backend = PostgresArrayBackend() if is_postgresql() else FallbackJsonBackend()

    return _backend


def reset_backend() -> None:
    """Reset the cached backend.  Useful for testing with different configs."""
    global _backend
    _backend = None
