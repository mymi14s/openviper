"""Backend adapters for openviper.contrib.geolocation.

Each backend class knows how to:

* Map a :class:`~openviper.contrib.geolocation.fields.PointField` to the
  appropriate SQL DDL column definition.
* Serialise :class:`~openviper.contrib.geolocation.geometry.Point` values
  to a format the backend driver accepts on write.
* Deserialise raw values returned by the driver into
  :class:`~openviper.contrib.geolocation.geometry.Point` instances on read.

Only PostgreSQL/PostGIS is a first-class supported backend.  A generic
fallback stores WKT strings in a TEXT column so that the field can be
used for prototyping with SQLite or another database that lacks spatial
extensions.

Usage::

    from openviper.contrib.geolocation.backends import get_backend

    backend = get_backend("postgresql")
    ddl = backend.column_ddl(field)            # e.g. GEOMETRY(Point,4326)
    db_value = backend.to_db(point)            # EWKT string
    py_value = backend.to_python(raw_value)    # Point instance
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from openviper.contrib.geolocation.geometry import Point

if TYPE_CHECKING:
    from openviper.contrib.geolocation.fields import PointField


class BaseGeoBackend:
    """Abstract base for geolocation database backends."""

    #: The canonical dialect name for this backend (lower-case).
    dialect: str = "generic"

    def column_ddl(self, field: PointField) -> str:
        """Return the SQL column type string for DDL generation.

        Args:
            field: The :class:`PointField` whose column type is required.

        Returns:
            SQL type string, e.g. ``'TEXT'``.
        """
        raise NotImplementedError

    def to_db(self, value: Point | None) -> Any:
        """Serialise a :class:`Point` for insertion into the database.

        Args:
            value: Point to serialise, or ``None``.

        Returns:
            A value suitable for the database driver.
        """
        raise NotImplementedError

    def to_python(self, raw: Any, srid: int = 4326) -> Point | None:
        """Deserialise a raw database value to a :class:`Point`.

        Args:
            raw: Raw value as returned by the database driver.
            srid: Fallback SRID when not embedded in the raw value.

        Returns:
            :class:`Point` instance, or ``None``.
        """
        raise NotImplementedError


class PostGISBackend(BaseGeoBackend):
    """PostgreSQL/PostGIS spatial backend.

    Uses ``GEOMETRY(Point, <srid>)`` or ``GEOGRAPHY(Point, <srid>)`` column
    types.  Values are written as EWKT strings that PostGIS parses via an
    implicit ``ST_GeomFromEWKT`` cast.  Values returned by the driver are
    hex-encoded WKB or plain WKT strings depending on the driver and
    configuration.
    """

    dialect = "postgresql"

    def column_ddl(self, field: PointField) -> str:
        return field.db_column_type

    def to_db(self, value: Point | None) -> str | None:
        if value is None:
            return None
        return value.to_ewkt()

    def to_python(self, raw: Any, srid: int = 4326) -> Point | None:
        if raw is None:
            return None
        if isinstance(raw, Point):
            return raw

        raw_str = str(raw).strip()

        # Hex-encoded WKB returned by some PostGIS drivers — delegate to shapely
        # if available, otherwise give a clear error.
        if raw_str and all(c in "0123456789abcdefABCDEF" for c in raw_str) and len(raw_str) > 20:
            try:
                from openviper.contrib.geolocation.utils import point_from_wkb_hex

                return point_from_wkb_hex(raw_str, srid=srid)
            except ImportError:
                pass

        # EWKT / WKT string
        from openviper.contrib.geolocation.fields import PointField as PointField_

        dummy = PointField_(srid=srid)
        return dummy.to_python(raw_str)


class FallbackTextBackend(BaseGeoBackend):
    """Generic fallback backend storing WKT in a TEXT column.

    Suitable for SQLite, MySQL, MSSQL, and any other database without PostGIS.
    Spatial indexing and distance queries are **not** supported; the field
    stores and retrieves point data only.
    """

    dialect = "generic"

    def column_ddl(self, field: PointField) -> str:
        return "TEXT"

    def to_db(self, value: Point | None) -> str | None:
        if value is None:
            return None
        return value.to_wkt()

    def to_python(self, raw: Any, srid: int = 4326) -> Point | None:
        if raw is None:
            return None
        if isinstance(raw, Point):
            return raw
        return Point.from_wkt(str(raw).strip(), srid=srid)


_BACKEND_REGISTRY: dict[str, BaseGeoBackend] = {
    "postgresql": PostGISBackend(),
    "postgres": PostGISBackend(),
    "postgis": PostGISBackend(),
    "generic": FallbackTextBackend(),
    "sqlite": FallbackTextBackend(),
    "mysql": FallbackTextBackend(),
    "mariadb": FallbackTextBackend(),
    "mssql": FallbackTextBackend(),
    "oracle": FallbackTextBackend(),
}


def get_backend(dialect: str) -> BaseGeoBackend:
    """Return the geo backend for the given database dialect name.

    Args:
        dialect: Database dialect string (case-insensitive), e.g. ``'postgresql'``.

    Returns:
        Appropriate :class:`BaseGeoBackend` instance.  Falls back to
        :class:`FallbackTextBackend` for unknown dialects.
    """
    return _BACKEND_REGISTRY.get(dialect.lower(), _BACKEND_REGISTRY["generic"])
