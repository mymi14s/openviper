"""Serializer support for PointField.

Provides JSON-safe serialization and input coercion for
:class:`~openviper.contrib.fields.geolocation.geometry.Point`
values, keeping geolocation-specific logic inside the geolocation package.
"""

from __future__ import annotations

import json
from typing import Any

from openviper.contrib.fields.geolocation.geometry import Point


def serialize_value(value: Any) -> dict[str, Any] | str | None:
    """Convert a Point value to a JSON-safe representation.

    Returns a GeoJSON dict ``{"type": "Point", "coordinates": [lon, lat]}``
    so the value is structured and self-describing in API responses.
    """
    if value is None:
        return None
    if isinstance(value, Point):
        return value.to_geojson()
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return value
    return None


def coerce_from_input(value: Any) -> str | dict[str, Any] | None:
    """Normalise incoming input for PointField storage.

    Accepts Point instances, GeoJSON dicts, WKT/EWKT strings, and None.
    Returns the value in a form that ``PointField.to_db`` can process.
    """
    if value is None:
        return None
    if isinstance(value, Point):
        return value.to_ewkt()
    if isinstance(value, dict):
        return json.dumps(value)
    if isinstance(value, str):
        return value
    return None
