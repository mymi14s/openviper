"""PointField — PostGIS-compatible geographic point field for OpenViper ORM.

This module provides a :class:`PointField` that stores a geographic
:class:`~openviper.contrib.geolocation.geometry.Point` value in PostgreSQL
using the PostGIS ``GEOMETRY(Point, 4326)`` column type.

For non-PostGIS databases (SQLite, etc.) the field falls back to storing
the WKT string in a TEXT column; the column type override is handled per
backend adapter in :mod:`openviper.contrib.geolocation.backends`.

Usage::

    from openviper.db import Model
    from openviper.contrib.geolocation import PointField, Point

    class Store(Model):
        name = CharField()
        location = PointField()

    # Create:
    store = await Store.objects.create(
        name="Shop",
        location=Point(-0.1276, 51.5074),
    )

    # Read back — returns a Point instance:
    shop = await Store.objects.get(id=store.id)
    print(shop.location.to_wkt())
"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa

from openviper.conf import settings
from openviper.contrib.geolocation.geometry import Point
from openviper.db import connection as _db_connection
from openviper.db.fields import Field


def _is_postgresql() -> bool:
    """Return True if the currently configured engine targets PostgreSQL."""
    try:
        if _db_connection._engine is not None:
            url = str(_db_connection._engine.url)
            return "postgresql" in url or "postgres" in url
    except Exception:
        pass
    # Fall back to settings when no engine has been configured yet.
    try:
        url = getattr(settings, "DATABASE_URL", "")
        return "postgresql" in url or "postgres" in url
    except Exception:
        pass
    return False


class _AdaptiveGeometryType(sa.types.TypeDecorator):  # type: ignore[type-arg]
    """SQLAlchemy TypeDecorator that wraps EWKT strings for PostGIS at runtime.

    Using a ``TypeDecorator`` (backed by ``sa.Text``) means the DDL column
    spec is always ``TEXT``, which SQLite and other non-PostGIS backends
    accept.  On PostgreSQL the ``bind_expression`` and ``column_expression``
    hooks delegate to PostGIS functions — but only when the active engine is
    actually PostgreSQL, so in-memory SQLite test databases are never asked
    to call ``ST_GeomFromEWKT``.
    """

    impl = sa.Text
    cache_ok = True

    def bind_expression(self, bindvalue: Any) -> Any:
        if _is_postgresql():
            return sa.func.ST_GeomFromEWKT(bindvalue)
        return bindvalue

    def column_expression(self, col: Any) -> Any:
        if _is_postgresql():
            return sa.func.ST_AsEWKT(col).label(col.key)
        return col


class _PostGISGeometryType(sa.types.UserDefinedType):  # type: ignore[type-arg]
    """Legacy PostGIS GEOMETRY UserDefinedType — kept for backwards compat.

    New code uses :class:`_AdaptiveGeometryType` instead.  This class is
    preserved so any serialised SA metadata that references it doesn't break.
    """

    cache_ok = True

    def get_col_spec(self, **kwargs: Any) -> str:
        return "geometry"

    def bind_expression(self, bindvalue: Any) -> Any:
        return sa.func.ST_GeomFromEWKT(bindvalue)

    def column_expression(self, col: Any) -> Any:
        return sa.func.ST_AsEWKT(col).label(col.key)


class PointField(Field):
    """ORM field that stores a geographic :class:`~openviper.contrib.geolocation.geometry.Point`.

    Column type on PostgreSQL with PostGIS: ``GEOMETRY(Point, 4326)``
    Column type on other backends: ``TEXT`` (WKT string)

    Args:
        srid: Spatial Reference ID (default 4326 = WGS-84).
        geography: When ``True``, use PostGIS ``GEOGRAPHY`` type instead of
            ``GEOMETRY`` (enables accurate distance calculations without
            explicit SRID transforms).
        **kwargs: Forwarded to :class:`~openviper.db.fields.Field`.

    Example::

        class Restaurant(Model):
            name = CharField()
            location = PointField(null=True)
    """

    _column_type = "GEOMETRY(Point,4326)"

    def __init__(
        self,
        srid: int = 4326,
        geography: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.srid = srid
        self.geography = geography

    @property
    def db_column_type(self) -> str:
        """Return the PostGIS column type string."""
        if self.geography:
            return f"GEOGRAPHY(Point,{self.srid})"
        return f"GEOMETRY(Point,{self.srid})"

    def to_python(self, value: Any) -> Point | None:
        """Convert a database value to a :class:`Point` instance.

        Handles:
        - ``None`` → ``None``
        - :class:`Point` → returned as-is
        - WKT string (``'POINT(lon lat)'``) → parsed
        - EWKT string (``'SRID=4326;POINT(lon lat)'``) → parsed, SRID respected
        - GeoJSON string (``'{"type":"Point","coordinates":[...]}'``) → parsed
        - dict (GeoJSON geometry) → :meth:`Point.from_geojson`
        """
        if value is None:
            return None
        if isinstance(value, Point):
            return value

        if isinstance(value, dict):
            return Point.from_geojson(value, srid=self.srid)

        if isinstance(value, str):
            stripped = value.strip()

            # EWKT: 'SRID=4326;POINT(lon lat)'
            if stripped.upper().startswith("SRID="):
                srid_part, _, wkt_part = stripped.partition(";")
                try:
                    parsed_srid = int(srid_part.split("=", 1)[1].strip())
                except ValueError, IndexError:
                    parsed_srid = self.srid
                return Point.from_wkt(wkt_part, srid=parsed_srid)

            # WKT: 'POINT(lon lat)'
            if stripped.upper().startswith("POINT"):
                return Point.from_wkt(stripped, srid=self.srid)

            # GeoJSON string: '{"type":"Point",...}'
            if stripped.startswith("{"):
                data = json.loads(stripped)
                return Point.from_geojson(data, srid=self.srid)

        return None

    def to_db(self, value: Any) -> str | None:
        """Serialise a :class:`Point` to a database-ready string (EWKT).

        Returns ``None`` for null values.  All other inputs are converted to
        their EWKT representation so that PostGIS can call
        ``ST_GeomFromEWKT(...)`` on the value.  On non-PostGIS backends the
        TEXT column stores the WKT string directly.
        """
        if value is None:
            return None
        if isinstance(value, Point):
            return value.to_ewkt()
        if isinstance(value, dict):
            pt = Point.from_geojson(value, srid=self.srid)
            return pt.to_ewkt()
        if isinstance(value, str):
            pt_or_none: Point | None = self.to_python(value)
            if pt_or_none is not None:
                return pt_or_none.to_ewkt()
        return None

    def __get__(self, obj: Any, objtype: Any = None) -> Any:
        if obj is None:
            return self
        raw = obj.__dict__.get(self.name)
        if isinstance(raw, str):
            result: Point | None = self.to_python(raw)
            obj.__dict__[self.name] = result
            return result
        return raw

    def __set__(self, obj: Any, value: Any) -> None:
        if isinstance(value, str):
            obj.__dict__[self.name] = self.to_python(value)
        else:
            obj.__dict__[self.name] = value

    def get_sa_type(self) -> sa.types.TypeEngine[Any]:
        """Return the SQLAlchemy column type for this field.

        Returns :class:`_AdaptiveGeometryType` which uses ``sa.Text`` for DDL
        (compatible with all backends) but wraps bind/column expressions for
        PostGIS at query time, so the right behaviour is used regardless of
        whether the engine is configured before or after the model class is
        imported.
        """
        return _AdaptiveGeometryType()

    def validate(self, value: Any) -> None:
        """Run Field-level validation, then confirm value is a valid Point."""
        super().validate(value)
        if value is not None and not isinstance(value, Point):
            # Try to coerce — raises InvalidPointError / ValueError if invalid
            self.to_python(value)
