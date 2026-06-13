"""Backend adapters for array field database columns.

Each backend maps ArrayField to SQL DDL, serialises list values for
writes, and deserialises raw driver values to Python lists.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from openviper.contrib.fields.dbutils import is_postgresql

if TYPE_CHECKING:
    from openviper.contrib.fields.array_fields.base import ArrayField


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


cached_backend: BaseArrayBackend | None = None


def get_backend() -> BaseArrayBackend:
    """Return the appropriate array backend based on the configured database."""
    global cached_backend
    if cached_backend is not None:
        return cached_backend

    cached_backend = PostgresArrayBackend() if is_postgresql() else FallbackJsonBackend()

    return cached_backend


def reset_backend() -> None:
    """Reset the cached backend.  Useful for testing with different configs."""
    global cached_backend
    cached_backend = None
