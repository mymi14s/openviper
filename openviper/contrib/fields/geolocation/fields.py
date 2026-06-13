"""PostGIS-compatible geographic point field for OpenViper ORM.

Stores Point values using GEOMETRY(Point, 4326) on PostgreSQL/PostGIS
and TEXT (WKT) on other backends.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql.base import PGDialect

from openviper.contrib.fields.dbutils import is_postgresql
from openviper.contrib.fields.geolocation.geometry import Point
from openviper.db.fields import Field

if TYPE_CHECKING:
    from openviper.contrib.fields.geolocation.types import GeoJSONObject, PointOwner


class GeoType(sa.types.UserDefinedType[object]):
    """Reflected PostGIS type placeholder for SQLAlchemy introspection."""

    def get_col_spec(self, **kwargs: object) -> str:
        return "GEOMETRY"


def register_postgis_types() -> None:
    """Register PostGIS spatial types with the PostgreSQL dialect."""
    for name in ("geometry", "geography", "point", "polygon", "linestring"):
        PGDialect.ischema_names.setdefault(name, GeoType)


register_postgis_types()


class AdaptiveGeometryType(sa.types.TypeDecorator[object]):
    """SQLAlchemy TypeDecorator wrapping EWKT for PostGIS at runtime."""

    impl = sa.Text
    cache_ok = True

    def bind_expression(self, bindvalue: object) -> sa.ColumnElement[object] | None:
        if is_postgresql():
            return sa.func.ST_GeomFromEWKT(bindvalue)
        return cast("sa.ColumnElement[object] | None", bindvalue)

    def column_expression(self, col: sa.ColumnElement[object]) -> sa.ColumnElement[object] | None:
        if is_postgresql():
            return sa.func.ST_AsEWKT(col).label(col.key)
        return col


class PostGISGeometryType(sa.types.UserDefinedType[object]):
    """Legacy PostGIS GEOMETRY type kept for backwards compat."""

    cache_ok = True

    def get_col_spec(self, **kwargs: object) -> str:
        return "geometry"

    def bind_expression(self, bindvalue: object) -> sa.ColumnElement[object] | None:
        return sa.func.ST_GeomFromEWKT(bindvalue)

    def column_expression(self, col: sa.ColumnElement[object]) -> sa.ColumnElement[object] | None:
        return sa.func.ST_AsEWKT(col).label(col.key)


class PointField(Field):
    """ORM field storing a geographic Point."""

    column_type = "GEOMETRY(Point,4326)"

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

    def to_python(self, value: object) -> Point | None:
        """Convert database value to Point instance."""
        if value is None:
            return None
        if isinstance(value, Point):
            return value

        if isinstance(value, dict):
            return Point.from_geojson(cast("GeoJSONObject", value), srid=self.srid)

        if isinstance(value, str):
            stripped = value.strip()

            # EWKT: 'SRID=4326;POINT(lon lat)'
            if stripped.upper().startswith("SRID="):
                srid_part, _, wkt_part = stripped.partition(";")
                try:
                    parsed_srid = int(srid_part.split("=", 1)[1].strip())
                except (ValueError, IndexError):  # fmt: skip
                    parsed_srid = self.srid
                return Point.from_wkt(wkt_part, srid=parsed_srid)

            # WKT: 'POINT(lon lat)'
            if stripped.upper().startswith("POINT"):
                return Point.from_wkt(stripped, srid=self.srid)

            # GeoJSON string: '{"type":"Point",...}'
            if stripped.startswith("{"):
                try:
                    data = json.loads(stripped)
                except json.JSONDecodeError:
                    return None
                return Point.from_geojson(cast("GeoJSONObject", data), srid=self.srid)

        return None

    def to_db(self, value: object) -> str | None:
        """Serialise Point to EWKT for database storage."""
        if value is None:
            return None
        if isinstance(value, Point):
            return value.to_ewkt()
        if isinstance(value, dict):
            pt = Point.from_geojson(cast("GeoJSONObject", value), srid=self.srid)
            return pt.to_ewkt()
        if isinstance(value, str):
            pt_or_none: Point | None = self.to_python(value)
            if pt_or_none is not None:
                return pt_or_none.to_ewkt()
        return None

    def __get__(
        self, obj: PointOwner | None, objtype: type[object] | None = None
    ) -> PointField | Point | None:
        if obj is None:
            return self
        raw = obj.__dict__.get(self.name)
        if isinstance(raw, str):
            result: Point | None = self.to_python(raw)
            obj.__dict__[self.name] = result
            return result
        return cast("Point | None", raw)

    def __set__(self, obj: PointOwner, value: object) -> None:
        if isinstance(value, str):
            obj.__dict__[self.name] = self.to_python(value)
        else:
            obj.__dict__[self.name] = value

    def get_sa_type(self) -> sa.types.TypeEngine[object]:
        """Return AdaptiveGeometryType for SQLAlchemy column."""
        return AdaptiveGeometryType()

    def validate(self, value: object) -> None:
        """Run Field-level validation, then confirm value is a valid Point."""
        super().validate(value)
        if value is not None and not isinstance(value, Point):
            # Try to coerce - raises InvalidPointError / ValueError if invalid
            self.to_python(value)
