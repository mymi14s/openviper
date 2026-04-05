Geolocation
===========

The ``openviper.contrib.geolocation`` package provides optional
PostGIS-compatible geolocation support for OpenViper models.  It adds
a :class:`~openviper.contrib.geolocation.geometry.Point` geometry class
and a :class:`~openviper.contrib.geolocation.fields.PointField` ORM field
that maps to ``GEOMETRY(Point, 4326)`` on PostgreSQL/PostGIS and falls
back to a WKT ``TEXT`` column on other databases.

The module has **no hard dependencies** on the core framework.  External
libraries (``shapely``, ``psycopg2-binary``) are optional and available
only when you install the ``Geolocation`` extras.

Overview
--------

* **Zero impact on core** — imports only when the module is first used.
* **PostGIS-ready** — ``GEOMETRY(Point, 4326)`` column DDL out of the box.
* **Fallback TEXT backend** — store WKT strings on any database.
* **Pure-Python** ``Point`` — no external library needed for basic use.
* **Haversine distance** — great-circle distance without shapely.
* **WKT / EWKT / GeoJSON** — three serialisation formats included.
* **shapely interop** — convert to/from ``shapely.geometry.Point`` when
  the extra is installed.
* **Clear error messages** — missing ``shapely`` produces an actionable
  ``DependencyMissingError`` with the install command.

Installation
------------

The module works without any extras for basic use.
To enable shapely integration and psycopg2 support::

    pip install openviper[Geolocation]

This installs:

* ``shapely>=2.0`` — hex-WKB decoding and Shapely interoperability.
* ``psycopg2-binary>=2.9`` — PostgreSQL driver for PostGIS databases.

Basic Usage
-----------

Define a model with a geographic location:

.. code-block:: python

    from openviper.db import Model
    from openviper.contrib.geolocation import Point, PointField
    from openviper.db.fields import AutoField, CharField


    class Store(Model):
        name: str = CharField(max_length=200)
        location: Point | None = PointField(null=True)

Create and query records — ORM operations are ``async``:

.. code-block:: python

    import asyncio

    from openviper.contrib.geolocation import Point, PointField
    from openviper.db import Model
    from openviper.db.fields import AutoField, CharField


    class Store(Model):
        id: int = AutoField()
        name: str = CharField(max_length=200)
        location: Point | None = PointField(null=True)


    async def create_store() -> Store:
        store: Store = await Store.objects.create(
            name="Shop",
            location=Point(-0.1276, 51.5074),  # longitude, latitude
        )
        return store


    async def fetch_store(store_id: int) -> None:
        shop: Store = await Store.objects.get(id=store_id)
        if shop.location is not None:
            print(shop.location.to_wkt())   # POINT(-0.1276 51.5074)
            print(shop.location.to_ewkt())  # SRID=4326;POINT(-0.1276 51.5074)


    async def main() -> None:
        store = await create_store()
        await fetch_store(store.id)

Point Geometry
--------------

.. code-block:: python

    from openviper.contrib.geolocation import Point

    # Construct from longitude, latitude (both are floats)
    london: Point = Point(-0.1276, 51.5074)
    paris: Point  = Point(2.3522, 48.8566)

    # WKT serialisation
    wkt: str = london.to_wkt()    # 'POINT(-0.1276 51.5074)'
    ewkt: str = london.to_ewkt()  # 'SRID=4326;POINT(-0.1276 51.5074)'

    # GeoJSON
    gj: dict[str, object] = london.to_geojson()
    # {'type': 'Point', 'coordinates': [-0.1276, 51.5074]}

    # Parse from WKT
    p: Point = Point.from_wkt("POINT(10.0 20.0)")

    # Parse from GeoJSON dict
    p = Point.from_geojson({"type": "Point", "coordinates": [10.0, 20.0]})

    # Haversine distance (metres, pure Python)
    distance: float = london.distance_to(paris)  # ~341 000 m

Coordinate validation:

* Longitude must be in **[-180, 180]**.
* Latitude must be in **[-90, 90]**.
* ``NaN`` and ``inf`` values are rejected with :class:`~openviper.contrib.geolocation.exceptions.InvalidPointError`.

PointField
----------

.. code-block:: python

    from openviper.contrib.geolocation import Point, PointField
    from openviper.db import Model
    from openviper.db.fields import AutoField, CharField


    class Restaurant(Model):
        id: int = AutoField()
        name: str = CharField(max_length=200)
        location: Point | None = PointField(null=True)

Constructor arguments:

.. list-table::
   :header-rows: 1

   * - Argument
     - Default
     - Description
   * - ``srid``
     - ``4326``
     - Spatial Reference ID (WGS-84).
   * - ``geography``
     - ``False``
     - Use PostGIS ``GEOGRAPHY`` type for accurate metric distances.
   * - ``null``
     - ``False``
     - Allow ``NULL`` values.
   * - ``db_index``
     - ``False``
     - Add a database index on the column.

On PostgreSQL/PostGIS the migration engine generates::

    location GEOMETRY(Point,4326)

or, with ``geography=True``::

    location GEOGRAPHY(Point,4326)

On all other databases the column is declared as ``TEXT`` and the value
is stored in WKT format.

Backends
--------

The backend layer handles database-specific serialisation.  It is
selected automatically via :func:`~openviper.contrib.geolocation.backends.get_backend`:

.. code-block:: python

    from openviper.contrib.geolocation.backends import BaseGeoBackend, get_backend

    backend: BaseGeoBackend = get_backend("postgresql")   # PostGISBackend
    backend = get_backend("sqlite")                       # FallbackTextBackend

Supported dialects:

.. list-table::
   :header-rows: 1

   * - Dialect strings
     - Backend class
     - Column type
   * - ``postgresql``, ``postgres``, ``postgis``
     - :class:`~openviper.contrib.geolocation.backends.PostGISBackend`
     - ``GEOMETRY(Point,<srid>)``
   * - ``sqlite``, ``mysql``, ``mariadb``, ``mssql``, ``oracle``, ``generic``
     - :class:`~openviper.contrib.geolocation.backends.FallbackTextBackend`
     - ``TEXT``

Utilities
---------

.. code-block:: python

    from openviper.contrib.geolocation import Point
    from openviper.contrib.geolocation.utils import (
        haversine_distance,
        parse_point,
        point_from_shapely,
        point_to_shapely,
    )

    london: Point = Point(-0.1276, 51.5074)
    paris: Point  = Point(2.3522, 48.8566)

    # Best-effort coercion from any input
    p: Point | None = parse_point((-0.1276, 51.5074))          # tuple
    p = parse_point([10.0, 20.0])                               # list
    p = parse_point("POINT(10.0 20.0)")                         # WKT string
    p = parse_point({"type": "Point", "coordinates": [10.0, 20.0]})  # GeoJSON dict

    # Pure-Python Haversine distance (returns metres)
    distance: float = haversine_distance(london, paris)

    # shapely interop (requires pip install openviper[Geolocation])
    import shapely.geometry

    shapely_pt: shapely.geometry.Point = point_to_shapely(london)
    back: Point = point_from_shapely(shapely_pt)

Errors
------

.. list-table::
   :header-rows: 1

   * - Exception
     - When raised
   * - :class:`~openviper.contrib.geolocation.exceptions.GeoLocationError`
     - Base class for all geolocation errors.
   * - :class:`~openviper.contrib.geolocation.exceptions.InvalidPointError`
     - Coordinate out of range, NaN/Inf, or malformed WKT/GeoJSON input.
   * - :class:`~openviper.contrib.geolocation.exceptions.DependencyMissingError`
     - Optional dependency (``shapely``) not installed.

``DependencyMissingError`` is a subclass of both
:class:`GeoLocationError` and :class:`ImportError`, so existing
``except ImportError`` guards continue to work.

Example:

.. code-block:: python

    from openviper.contrib.geolocation import Point
    from openviper.contrib.geolocation.exceptions import DependencyMissingError
    from openviper.contrib.geolocation.utils import point_to_shapely

    my_point: Point = Point(-0.1276, 51.5074)
    try:
        s = point_to_shapely(my_point)
    except DependencyMissingError as exc:
        print(exc)  # "pip install openviper[Geolocation]"

Settings & Configuration
------------------------

No framework-level settings are required.  The recommended pattern is to
configure PointField options directly on the field and pass connection
details through the standard OpenViper ``DATABASE`` setting.

Example ``settings.py`` with typed annotations:

.. code-block:: python

    from __future__ import annotations

    # Database — PostGIS requires asyncpg or psycopg2-binary
    DATABASE: dict[str, str | int] = {
        "ENGINE": "postgresql",
        "NAME": "mydb",
        "USER": "postgres",
        "PASSWORD": "secret",
        "HOST": "localhost",
        "PORT": 5432,
    }

    # Optional: limit JSON/file sizes (unrelated to geolocation, shown for completeness)
    MAX_FILE_SIZE: int = 10 * 1024 * 1024    # 10 MB
    MAX_JSON_SIZE: int = 1 * 1024 * 1024     # 1 MB

    # MEDIA_DIR is used by FileField; geolocation does not write files
    MEDIA_DIR: str = "./media"

    INSTALLED_APPS: list[str] = [
        "myapp",
    ]

Per-field configuration example on a model:

.. code-block:: python

    from openviper.contrib.geolocation import Point, PointField
    from openviper.db import Model
    from openviper.db.fields import AutoField, CharField


    class Location(Model):
        """Stores a named geographic location."""

        id: int = AutoField()
        name: str = CharField(max_length=200)

        # Standard WGS-84 geometry column
        point: Point | None = PointField(null=True, srid=4326)

        # Geography type — enables accurate ST_Distance without SRID transforms
        point_geo: Point | None = PointField(
            null=True,
            srid=4326,
            geography=True,
        )

        # Indexed geometry for spatial queries
        point_indexed: Point | None = PointField(
            null=True,
            db_index=True,
        )

API Reference
-------------

.. automodule:: openviper.contrib.geolocation
   :members:

.. autoclass:: openviper.contrib.geolocation.geometry.Point
   :members:

.. autoclass:: openviper.contrib.geolocation.fields.PointField
   :members:

.. automodule:: openviper.contrib.geolocation.backends
   :members:

.. automodule:: openviper.contrib.geolocation.utils
   :members:

.. automodule:: openviper.contrib.geolocation.exceptions
   :members:
