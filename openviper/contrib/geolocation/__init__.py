"""openviper.contrib.geolocation — optional PostGIS-compatible geolocation support.

This package provides a :class:`~openviper.contrib.geolocation.fields.PointField`
ORM field and a :class:`~openviper.contrib.geolocation.geometry.Point` geometry
class for working with geographic coordinates in OpenViper models.

The module itself has **no hard dependencies** on external packages.
Optional shapely integration (WKB decoding, Shapely interop) becomes
available when you install the ``Geolocation`` extras::

    pip install openviper[Geolocation]

Basic usage::

    from openviper.db import Model
    from openviper.contrib.geolocation import PointField, Point

    class Store(Model):
        name = CharField()
        location = PointField()

    # Create a store with a geographic location:
    store = await Store.objects.create(
        name="Shop",
        location=Point(-0.1276, 51.5074),
    )

Public API
----------
Point
    Geographic point (longitude, latitude) in WGS-84.
PointField
    ORM field that maps to ``GEOMETRY(Point, 4326)`` on PostgreSQL/PostGIS
    and ``TEXT`` (WKT) on other databases.

Utility helpers
---------------
parse_point(value) -> Point | None
    Best-effort conversion of arbitrary input to a :class:`Point`.
haversine_distance(a, b) -> float
    Great-circle distance between two points in metres (pure Python).
get_backend(dialect) -> BaseGeoBackend
    Return the database backend adapter for a given dialect string.
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
