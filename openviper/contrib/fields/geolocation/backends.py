"""Backend adapters for geolocation database columns.

Each backend maps PointField to SQL DDL, serialises Point values
for writes, and deserialises raw driver values to Point instances.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from openviper.contrib.fields.geolocation.geometry import Point
from openviper.contrib.fields.geolocation.utils import point_from_wkb_hex

if TYPE_CHECKING:
    from openviper.contrib.fields.geolocation.fields import PointField
    from openviper.contrib.fields.geolocation.types import GeoJSONObject


class BaseGeoBackend:
    """Abstract base for geolocation database backends."""

    dialect: str = "generic"

    def column_ddl(self, field: PointField) -> str:
        """Return SQL column type string for DDL generation."""
        raise NotImplementedError

    def to_db(self, value: Point | None) -> object:
        """Serialise Point for database insertion."""
        raise NotImplementedError

    def to_python(self, raw: object, srid: int = 4326) -> Point | None:
        """Deserialise raw database value to Point."""
        raise NotImplementedError


class PostGISBackend(BaseGeoBackend):
    """PostgreSQL/PostGIS spatial backend using EWKT."""

    dialect = "postgresql"

    def column_ddl(self, field: PointField) -> str:
        return field.db_column_type

    def to_db(self, value: Point | None) -> str | None:
        if value is None:
            return None
        return value.to_ewkt()

    def to_python(self, raw: object, srid: int = 4326) -> Point | None:
        if raw is None:
            return None
        if isinstance(raw, Point):
            return raw

        raw_str = str(raw).strip()

        # Hex WKB from PostGIS - delegate to shapely if available.
        if raw_str and all(c in "0123456789abcdefABCDEF" for c in raw_str) and len(raw_str) > 20:
            return point_from_wkb_hex(raw_str, srid=srid)

        # EWKT: 'SRID=4326;POINT(lon lat)'
        if raw_str.upper().startswith("SRID="):
            srid_part, _, wkt_part = raw_str.partition(";")
            try:
                parsed_srid = int(srid_part.split("=", 1)[1].strip())
            except (ValueError, IndexError):  # fmt: skip
                parsed_srid = srid
            return Point.from_wkt(wkt_part, srid=parsed_srid)

        # WKT: 'POINT(lon lat)'
        if raw_str.upper().startswith("POINT"):
            return Point.from_wkt(raw_str, srid=srid)

        return None


class FallbackTextBackend(BaseGeoBackend):
    """Generic fallback storing WKT in TEXT columns."""

    dialect = "generic"

    def column_ddl(self, field: PointField) -> str:
        return "TEXT"

    def to_db(self, value: Point | None) -> str | None:
        if value is None:
            return None
        return value.to_wkt()

    def to_python(self, raw: object, srid: int = 4326) -> Point | None:
        if raw is None:
            return None
        if isinstance(raw, Point):
            return raw
        if isinstance(raw, dict):
            return Point.from_geojson(cast("GeoJSONObject", raw), srid=srid)
        if isinstance(raw, str):
            stripped = raw.strip()
            if stripped.upper().startswith("SRID="):
                srid_part, _, wkt_part = stripped.partition(";")
                try:
                    parsed_srid = int(srid_part.split("=", 1)[1].strip())
                except (ValueError, IndexError):
                    parsed_srid = srid
                return Point.from_wkt(wkt_part, srid=parsed_srid)
            if stripped.upper().startswith("POINT"):
                return Point.from_wkt(stripped, srid=srid)
            if stripped.startswith("{"):
                try:
                    data = json.loads(stripped)
                except json.JSONDecodeError:
                    return None
                return Point.from_geojson(cast("GeoJSONObject", data), srid=srid)
        return None


BACKEND_REGISTRY: dict[str, BaseGeoBackend] = {
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
    """Return geo backend for dialect, falling back to generic."""
    return BACKEND_REGISTRY.get(dialect.lower(), BACKEND_REGISTRY["generic"])
