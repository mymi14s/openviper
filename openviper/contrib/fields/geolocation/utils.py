"""Utility helpers for geolocation.

Requires shapely for WKB and geometry conversion helpers.
Pure-Python helpers (parse_point, haversine_distance) have no
external requirements.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import shapely.geometry as shapely_geometry_module
import shapely.wkb as shapely_wkb_module

from openviper.contrib.fields.geolocation.geometry import Point

if TYPE_CHECKING:
    from openviper.contrib.fields.geolocation.types import (
        GeoJSONObject,
        PointInput,
        ShapelyGeometryModule,
        ShapelyPoint,
    )


def require_shapely() -> ShapelyGeometryModule:
    """Return the shapely.geometry module."""
    return cast("ShapelyGeometryModule", shapely_geometry_module)


def point_to_shapely(point: Point) -> ShapelyPoint:
    """Convert Point to shapely.geometry.Point."""
    sg = require_shapely()
    return sg.Point(point.longitude, point.latitude)


def point_from_shapely(shapely_point: ShapelyPoint, srid: int = 4326) -> Point:
    """Convert shapely.geometry.Point to Point."""
    require_shapely()
    return Point(shapely_point.x, shapely_point.y, srid=srid)


def point_from_wkb_hex(hex_str: str, srid: int = 4326) -> Point:
    """Decode hex-encoded WKB string from PostGIS into Point."""
    geom = shapely_wkb_module.loads(hex_str, hex=True)
    return Point(geom.x, geom.y, srid=srid)


def parse_point(value: PointInput | Point, srid: int = 4326) -> Point | None:
    """Best-effort conversion of arbitrary value to Point."""
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
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError:
                return None
            return Point.from_geojson(cast("GeoJSONObject", data), srid=srid)
        return Point.from_wkt(stripped, srid=srid)
    return None


def haversine_distance(point_a: Point, point_b: Point) -> float:
    """Haversine great-circle distance between two points in metres."""
    return point_a.distance_to(point_b)
