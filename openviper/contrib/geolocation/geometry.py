"""Point geometry class for openviper.contrib.geolocation.

This module is dependency-free; it does **not** import shapely.
The optional shapely integration lives in :mod:`openviper.contrib.geolocation.utils`.
"""

from __future__ import annotations

import math
from typing import Any

from openviper.contrib.geolocation.exceptions import InvalidPointError

_LON_MIN = -180.0
_LON_MAX = 180.0
_LAT_MIN = -90.0
_LAT_MAX = 90.0


class Point:
    """Represents a geographic point as (longitude, latitude) in WGS-84.

    Args:
        longitude: East-west position in decimal degrees (-180 to 180).
        latitude: North-south position in decimal degrees (-90 to 90).
        srid: Spatial Reference ID (default 4326 = WGS-84).

    Raises:
        InvalidPointError: If coordinate values are out of range or NaN/Inf.

    Example::

        from openviper.contrib.geolocation import Point

        p = Point(-0.1276, 51.5074)  # London
        print(p.to_wkt())            # 'POINT(-0.1276 51.5074)'
    """

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
            raise InvalidPointError(f"longitude must be a finite number, got {longitude!r}")
        if math.isnan(latitude) or math.isinf(latitude):
            raise InvalidPointError(f"latitude must be a finite number, got {latitude!r}")
        if not (_LON_MIN <= longitude <= _LON_MAX):
            raise InvalidPointError(
                f"longitude {longitude!r} is out of range [{_LON_MIN}, {_LON_MAX}]"
            )
        if not (_LAT_MIN <= latitude <= _LAT_MAX):
            raise InvalidPointError(
                f"latitude {latitude!r} is out of range [{_LAT_MIN}, {_LAT_MAX}]"
            )

        self.longitude = longitude
        self.latitude = latitude
        self.srid = int(srid)

    def to_wkt(self) -> str:
        """Return the Well-Known Text (WKT) representation.

        Returns:
            WKT string, e.g. ``'POINT(-0.1276 51.5074)'``.
        """
        return f"POINT({self.longitude} {self.latitude})"

    def to_ewkt(self) -> str:
        """Return Extended WKT (EWKT) representation including SRID.

        Returns:
            EWKT string, e.g. ``'SRID=4326;POINT(-0.1276 51.5074)'``.
        """
        return f"SRID={self.srid};{self.to_wkt()}"

    def to_geojson(self) -> dict[str, Any]:
        """Return a GeoJSON-compatible dict representation.

        Returns:
            GeoJSON geometry dict with ``type`` and ``coordinates`` keys.
        """
        return {"type": "Point", "coordinates": [self.longitude, self.latitude]}

    def distance_to(self, other: Point) -> float:
        """Calculate the Haversine distance to another point in metres.

        Args:
            other: The target :class:`Point`.

        Returns:
            Great-circle distance in metres.
        """
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
        """Parse a WKT string into a :class:`Point`.

        Args:
            wkt: WKT string, e.g. ``'POINT(-0.1276 51.5074)'``.
            srid: Spatial Reference ID to assign (default 4326).

        Returns:
            New :class:`Point` instance.

        Raises:
            InvalidPointError: If the WKT string cannot be parsed.
        """
        stripped = wkt.strip()
        if not stripped.upper().startswith("POINT"):
            raise InvalidPointError(f"Cannot parse WKT: expected POINT geometry, got {wkt!r}")
        try:
            inner = stripped[stripped.index("(") + 1 : stripped.rindex(")")]
            lon_str, lat_str = inner.strip().split()
            return cls(float(lon_str), float(lat_str), srid=srid)
        except (ValueError, IndexError) as exc:
            raise InvalidPointError(f"Cannot parse WKT {wkt!r}: {exc}") from exc

    @classmethod
    def from_geojson(cls, data: dict[str, Any], srid: int = 4326) -> Point:
        """Construct a :class:`Point` from a GeoJSON geometry dict.

        Args:
            data: GeoJSON geometry dict with ``type`` and ``coordinates`` keys.
            srid: Spatial Reference ID to assign (default 4326).

        Returns:
            New :class:`Point` instance.

        Raises:
            InvalidPointError: If the dict does not represent a valid GeoJSON Point.
        """
        if data.get("type") != "Point":
            raise InvalidPointError(f"GeoJSON type must be 'Point', got {data.get('type')!r}")
        coords = data.get("coordinates")
        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
            raise InvalidPointError(
                f"GeoJSON Point coordinates must be [longitude, latitude], got {coords!r}"
            )
        return cls(float(coords[0]), float(coords[1]), srid=srid)
