"""Point geometry class for geolocation.

Dependency-free; shapely integration is in utils.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from openviper.contrib.fields.geolocation.exceptions import InvalidPointError

if TYPE_CHECKING:
    from openviper.contrib.fields.geolocation.types import GeoJSONObject, GeoJSONOutput

LON_MIN = -180.0
LON_MAX = 180.0
LAT_MIN = -90.0
LAT_MAX = 90.0


class Point:
    """Geographic point as (longitude, latitude) in WGS-84."""

    __slots__ = ("latitude", "longitude", "srid")

    def __init__(
        self,
        longitude: float,
        latitude: float,
        srid: int = 4326,
    ) -> None:
        longitude = float(longitude)
        latitude = float(latitude)

        if math.isnan(longitude) or math.isinf(longitude):
            msg = f"longitude must be a finite number, got {longitude!r}"
            raise InvalidPointError(msg)
        if math.isnan(latitude) or math.isinf(latitude):
            msg = f"latitude must be a finite number, got {latitude!r}"
            raise InvalidPointError(msg)
        if longitude < LON_MIN or longitude > LON_MAX:
            raise InvalidPointError(
                f"longitude {longitude!r} is out of range [{LON_MIN}, {LON_MAX}]"
            )
        if latitude < LAT_MIN or latitude > LAT_MAX:
            msg = f"latitude {latitude!r} is out of range [{LAT_MIN}, {LAT_MAX}]"
            raise InvalidPointError(msg)

        self.longitude = longitude
        self.latitude = latitude
        self.srid = int(srid)

    def to_wkt(self) -> str:
        """Return WKT representation."""
        return f"POINT({self.longitude} {self.latitude})"

    def to_ewkt(self) -> str:
        """Return EWKT representation including SRID."""
        return f"SRID={self.srid};{self.to_wkt()}"

    def to_geojson(self) -> GeoJSONOutput:
        """Return GeoJSON-compatible dict."""
        return {"type": "Point", "coordinates": [self.longitude, self.latitude]}

    def distance_to(self, other: Point) -> float:
        """Haversine great-circle distance to other point in metres."""
        earth_radius_m = 6_371_000.0
        lat1 = math.radians(self.latitude)
        lat2 = math.radians(other.latitude)
        d_lat = math.radians(other.latitude - self.latitude)
        d_lon = math.radians(other.longitude - self.longitude)

        a = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return earth_radius_m * c

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Point):
            return NotImplemented
        return (
            math.isclose(self.longitude, other.longitude, rel_tol=1e-9)
            and math.isclose(self.latitude, other.latitude, rel_tol=1e-9)
            and self.srid == other.srid
        )

    def __hash__(self) -> int:
        return hash((self.longitude, self.latitude, self.srid))

    def __repr__(self) -> str:
        return f"Point(longitude={self.longitude}, latitude={self.latitude}, srid={self.srid})"

    def __str__(self) -> str:
        return self.to_wkt()

    @classmethod
    def from_wkt(cls, wkt: str, srid: int = 4326) -> Point:
        """Parse WKT string into Point."""
        stripped = wkt.strip()
        if not stripped.upper().startswith("POINT"):
            msg = f"Cannot parse WKT: expected POINT geometry, got {wkt!r}"
            raise InvalidPointError(msg)
        try:
            inner = stripped[stripped.index("(") + 1 : stripped.rindex(")")]
            lon_str, lat_str = inner.strip().split()
            return cls(float(lon_str), float(lat_str), srid=srid)
        except (ValueError, IndexError) as exc:
            msg = f"Cannot parse WKT {wkt!r}: {exc}"
            raise InvalidPointError(msg) from exc

    @classmethod
    def from_geojson(cls, data: GeoJSONObject, srid: int = 4326) -> Point:
        """Construct Point from GeoJSON geometry dict."""
        if data.get("type") != "Point":
            msg = f"GeoJSON type must be 'Point', got {data.get('type')!r}"
            raise InvalidPointError(msg)
        coords = data.get("coordinates")
        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
            msg = f"GeoJSON Point coordinates must be [longitude, latitude], got {coords!r}"
            raise InvalidPointError(msg)
        return cls(float(coords[0]), float(coords[1]), srid=srid)
