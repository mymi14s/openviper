"""PostGIS-compatible geolocation support.

Provides PointField ORM field and Point geometry class.
Shapely integration available via the Geolocation extras.
"""

from __future__ import annotations

from openviper.contrib.geolocation.backends import BaseGeoBackend, get_backend
from openviper.contrib.geolocation.exceptions import (
    DependencyMissingError,
    GeoLocationError,
    InvalidPointError,
)
from openviper.contrib.geolocation.fields import PointField
from openviper.contrib.geolocation.geometry import Point
from openviper.contrib.geolocation.utils import haversine_distance, parse_point

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
