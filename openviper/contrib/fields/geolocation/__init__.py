"""PostGIS-compatible geolocation support.

Provides PointField ORM field and Point geometry class.
Shapely integration available via the Geolocation extras.
"""

from __future__ import annotations

from openviper.contrib.fields.geolocation.backends import BaseGeoBackend, get_backend
from openviper.contrib.fields.geolocation.exceptions import (
    DependencyMissingError,
    GeoLocationError,
    InvalidPointError,
)
from openviper.contrib.fields.geolocation.fields import PointField
from openviper.contrib.fields.geolocation.geometry import Point
from openviper.contrib.fields.geolocation.utils import haversine_distance, parse_point

__all__ = [
    "BaseGeoBackend",
    "DependencyMissingError",
    "GeoLocationError",
    "InvalidPointError",
    "Point",
    "PointField",
    "get_backend",
    "haversine_distance",
    "parse_point",
]
