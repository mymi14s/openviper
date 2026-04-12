"""Utility helpers for openviper.contrib.geolocation.

Functions that depend on *optional* packages (shapely, psycopg2) are
guarded by dependency checks.  All other helpers are pure-Python and
have no external requirements.
"""

from __future__ import annotations

import json
from typing import Any

from openviper.contrib.geolocation.exceptions import DependencyMissingError
from openviper.contrib.geolocation.geometry import Point


def require_shapely() -> Any:
    """Import and return the ``shapely.geometry`` module.

    Raises:
        DependencyMissingError: If ``shapely`` is not installed.
    """
    try:
        import shapely.geometry as _sg

        return _sg
    except ImportError as exc:
        raise DependencyMissingError("shapely>=2.0") from exc


def point_to_shapely(point: Point) -> Any:
    """Convert a :class:`~openviper.contrib.geolocation.geometry.Point` to a
    ``shapely.geometry.Point``.

    Args:
        point: The point to convert.

    Returns:
        ``shapely.geometry.Point`` instance.

    Raises:
        DependencyMissingError: If ``shapely`` is not installed.
    """
    sg = require_shapely()
    return sg.Point(point.longitude, point.latitude)


def point_from_shapely(shapely_point: Any, srid: int = 4326) -> Point:
    """Convert a ``shapely.geometry.Point`` to an OpenViper
    :class:`~openviper.contrib.geolocation.geometry.Point`.

    Args:
        shapely_point: A ``shapely.geometry.Point`` instance.
        srid: Spatial Reference ID to assign (default 4326).

    Returns:
        :class:`~openviper.contrib.geolocation.geometry.Point` instance.

    Raises:
        DependencyMissingError: If ``shapely`` is not installed.
    """
    require_shapely()
    return Point(shapely_point.x, shapely_point.y, srid=srid)


def point_from_wkb_hex(hex_str: str, srid: int = 4326) -> Point:
    """Decode a hex-encoded WKB string returned by PostGIS into a :class:`Point`.

    This function requires ``shapely>=2.0``.

    Args:
        hex_str: Hex-encoded WKB bytes as a string.
        srid: Spatial Reference ID to assign if not embedded in the WKB (default 4326).

    Returns:
        :class:`~openviper.contrib.geolocation.geometry.Point` instance.

    Raises:
        DependencyMissingError: If ``shapely`` is not installed.
    """
    try:
        from shapely import wkb as shapely_wkb
    except ImportError as exc:
        raise DependencyMissingError("shapely>=2.0") from exc

    geom = shapely_wkb.loads(hex_str, hex=True)
    return Point(geom.x, geom.y, srid=srid)


def parse_point(value: Any, srid: int = 4326) -> Point | None:
    """Best-effort conversion of an arbitrary value to a :class:`Point`.

    Accepts:
    - :class:`Point` → returned unchanged
    - WKT string (``'POINT(lon lat)'``)
    - EWKT string (``'SRID=4326;POINT(lon lat)'``)
    - GeoJSON dict (``{"type": "Point", "coordinates": [lon, lat]}``)
    - GeoJSON string
    - ``(longitude, latitude)`` tuple or list
    - ``None`` → ``None``

    Args:
        value: Input value to parse.
        srid: Default SRID when not embedded in the value.

    Returns:
        :class:`Point` or ``None``.
    """
    if value is None:
        return None
    if isinstance(value, Point):
        return value
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return Point(float(value[0]), float(value[1]), srid=srid)
    if isinstance(value, dict):
        return Point.from_geojson(value, srid=srid)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{"):
            data = json.loads(stripped)
            return Point.from_geojson(data, srid=srid)
        return Point.from_wkt(stripped, srid=srid)
    return None


def haversine_distance(point_a: Point, point_b: Point) -> float:
    """Return the Haversine distance between two points in metres.

    This is a pure-Python implementation that requires no external libraries.
    For high-accuracy geodetic calculations use the PostGIS ``ST_Distance``
    function or shapely with pyproj.

    Args:
        point_a: First geographic point.
        point_b: Second geographic point.

    Returns:
        Distance in metres (float).
    """
    return point_a.distance_to(point_b)
