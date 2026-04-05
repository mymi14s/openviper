"""Unit tests for openviper.contrib.geolocation."""

from __future__ import annotations

import json

import pytest

from openviper.contrib.geolocation import (
    GeoLocationError,
    InvalidPointError,
    Point,
    PointField,
    get_backend,
    haversine_distance,
    parse_point,
)
from openviper.contrib.geolocation.backends import (
    FallbackTextBackend,
    PostGISBackend,
)
from openviper.contrib.geolocation.exceptions import DependencyMissingError as _DepMissing

# ---------------------------------------------------------------------------
# Point geometry
# ---------------------------------------------------------------------------


class TestPointConstruction:
    """Point accepts valid coordinates and rejects invalid ones."""

    def test_valid_longitude_latitude(self) -> None:
        p = Point(-0.1276, 51.5074)
        assert p.longitude == -0.1276
        assert p.latitude == 51.5074

    def test_default_srid_is_4326(self) -> None:
        p = Point(0.0, 0.0)
        assert p.srid == 4326

    def test_custom_srid(self) -> None:
        p = Point(10.0, 20.0, srid=27700)
        assert p.srid == 27700

    def test_boundary_longitude_negative_180(self) -> None:
        p = Point(-180.0, 0.0)
        assert p.longitude == -180.0

    def test_boundary_longitude_positive_180(self) -> None:
        p = Point(180.0, 0.0)
        assert p.longitude == 180.0

    def test_boundary_latitude_negative_90(self) -> None:
        p = Point(0.0, -90.0)
        assert p.latitude == -90.0

    def test_boundary_latitude_positive_90(self) -> None:
        p = Point(0.0, 90.0)
        assert p.latitude == 90.0

    def test_longitude_too_low_raises(self) -> None:
        with pytest.raises(InvalidPointError):
            Point(-180.001, 0.0)

    def test_longitude_too_high_raises(self) -> None:
        with pytest.raises(InvalidPointError):
            Point(180.001, 0.0)

    def test_latitude_too_low_raises(self) -> None:
        with pytest.raises(InvalidPointError):
            Point(0.0, -90.001)

    def test_latitude_too_high_raises(self) -> None:
        with pytest.raises(InvalidPointError):
            Point(0.0, 90.001)

    def test_nan_longitude_raises(self) -> None:
        with pytest.raises(InvalidPointError):
            Point(float("nan"), 0.0)

    def test_inf_longitude_raises(self) -> None:
        with pytest.raises(InvalidPointError):
            Point(float("inf"), 0.0)

    def test_nan_latitude_raises(self) -> None:
        with pytest.raises(InvalidPointError):
            Point(0.0, float("nan"))

    def test_inf_latitude_raises(self) -> None:
        with pytest.raises(InvalidPointError):
            Point(0.0, float("-inf"))

    def test_string_inputs_coerced(self) -> None:
        p = Point("10.5", "20.5")
        assert p.longitude == 10.5
        assert p.latitude == 20.5


class TestPointWKT:
    """WKT serialisation and parsing round-trips correctly."""

    def test_to_wkt_format(self) -> None:
        p = Point(-0.1276, 51.5074)
        assert p.to_wkt() == "POINT(-0.1276 51.5074)"

    def test_to_ewkt_includes_srid(self) -> None:
        p = Point(-0.1276, 51.5074, srid=4326)
        assert p.to_ewkt() == "SRID=4326;POINT(-0.1276 51.5074)"

    def test_from_wkt_round_trip(self) -> None:
        p = Point(-0.1276, 51.5074)
        parsed = Point.from_wkt(p.to_wkt())
        assert parsed == p

    def test_from_wkt_whitespace_tolerant(self) -> None:
        p = Point.from_wkt("  POINT( -10.0  40.5 )  ")
        assert p.longitude == -10.0
        assert p.latitude == 40.5

    def test_from_wkt_non_point_raises(self) -> None:
        with pytest.raises(InvalidPointError):
            Point.from_wkt("LINESTRING(0 0, 1 1)")

    def test_from_wkt_malformed_raises(self) -> None:
        with pytest.raises(InvalidPointError):
            Point.from_wkt("POINT(bad data here)")

    def test_str_returns_wkt(self) -> None:
        p = Point(1.0, 2.0)
        assert str(p) == "POINT(1.0 2.0)"


class TestPointGeoJSON:
    """GeoJSON serialisation and parsing."""

    def test_to_geojson_structure(self) -> None:
        p = Point(-0.1276, 51.5074)
        gj = p.to_geojson()
        assert gj["type"] == "Point"
        assert gj["coordinates"] == [-0.1276, 51.5074]

    def test_from_geojson_round_trip(self) -> None:
        p = Point(10.0, 20.0)
        parsed = Point.from_geojson(p.to_geojson())
        assert parsed == p

    def test_from_geojson_wrong_type_raises(self) -> None:
        with pytest.raises(InvalidPointError):
            Point.from_geojson({"type": "LineString", "coordinates": [[0, 0], [1, 1]]})

    def test_from_geojson_missing_coordinates_raises(self) -> None:
        with pytest.raises(InvalidPointError):
            Point.from_geojson({"type": "Point", "coordinates": []})

    def test_from_geojson_extra_coordinate_ignored(self) -> None:
        p = Point.from_geojson({"type": "Point", "coordinates": [10.0, 20.0, 100.0]})
        assert p.longitude == 10.0
        assert p.latitude == 20.0


class TestPointEquality:
    """Point equality and hashing."""

    def test_equal_points(self) -> None:
        assert Point(1.0, 2.0) == Point(1.0, 2.0)

    def test_unequal_longitude(self) -> None:
        assert Point(1.0, 2.0) != Point(1.1, 2.0)

    def test_unequal_srid(self) -> None:
        assert Point(1.0, 2.0, srid=4326) != Point(1.0, 2.0, srid=27700)

    def test_hash_equal_for_equal_points(self) -> None:
        assert hash(Point(1.0, 2.0)) == hash(Point(1.0, 2.0))

    def test_hash_usable_in_set(self) -> None:
        s = {Point(1.0, 2.0), Point(1.0, 2.0), Point(3.0, 4.0)}
        assert len(s) == 2

    def test_not_equal_to_non_point(self) -> None:
        # Python's == operator converts NotImplemented to False
        assert (Point(1.0, 2.0) == "something") is False


class TestPointDistance:
    """Haversine distance calculation."""

    def test_zero_distance_same_point(self) -> None:
        p = Point(0.0, 0.0)
        assert p.distance_to(p) == pytest.approx(0.0)

    def test_london_to_paris_approx(self) -> None:
        london = Point(-0.1276, 51.5074)
        paris = Point(2.3522, 48.8566)
        distance = london.distance_to(paris)
        # known approximate distance ~341 km
        assert 330_000 < distance < 355_000

    def test_haversine_distance_helper_matches(self) -> None:
        a = Point(-0.1276, 51.5074)
        b = Point(2.3522, 48.8566)
        assert haversine_distance(a, b) == pytest.approx(a.distance_to(b))

    def test_distance_is_symmetric(self) -> None:
        a = Point(10.0, 20.0)
        b = Point(30.0, 40.0)
        assert a.distance_to(b) == pytest.approx(b.distance_to(a))


# ---------------------------------------------------------------------------
# PointField
# ---------------------------------------------------------------------------


class TestPointFieldToPython:
    """PointField.to_python converts raw DB values to Point instances."""

    def setup_method(self) -> None:
        self.field = PointField()
        self.field.name = "location"

    def test_none_returns_none(self) -> None:
        assert self.field.to_python(None) is None

    def test_point_passthrough(self) -> None:
        p = Point(1.0, 2.0)
        assert self.field.to_python(p) is p

    def test_wkt_string_parsed(self) -> None:
        result = self.field.to_python("POINT(10.0 20.0)")
        assert isinstance(result, Point)
        assert result.longitude == 10.0
        assert result.latitude == 20.0

    def test_ewkt_string_parsed(self) -> None:
        result = self.field.to_python("SRID=4326;POINT(10.0 20.0)")
        assert isinstance(result, Point)
        assert result.srid == 4326

    def test_geojson_string_parsed(self) -> None:
        gj = json.dumps({"type": "Point", "coordinates": [5.0, 10.0]})
        result = self.field.to_python(gj)
        assert isinstance(result, Point)
        assert result.longitude == 5.0

    def test_geojson_dict_parsed(self) -> None:
        result = self.field.to_python({"type": "Point", "coordinates": [5.0, 10.0]})
        assert isinstance(result, Point)
        assert result.latitude == 10.0

    def test_invalid_string_returns_none(self) -> None:
        assert self.field.to_python("not-a-geometry") is None


class TestPointFieldToDB:
    """PointField.to_db serialises Point values to EWKT for the database."""

    def setup_method(self) -> None:
        self.field = PointField(srid=4326)
        self.field.name = "location"

    def test_none_returns_none(self) -> None:
        assert self.field.to_db(None) is None

    def test_point_serialised_to_ewkt(self) -> None:
        p = Point(-0.1276, 51.5074)
        result = self.field.to_db(p)
        assert result == "SRID=4326;POINT(-0.1276 51.5074)"

    def test_geojson_dict_serialised(self) -> None:
        result = self.field.to_db({"type": "Point", "coordinates": [10.0, 20.0]})
        assert result is not None
        assert "POINT" in result

    def test_wkt_string_round_trips(self) -> None:
        result = self.field.to_db("POINT(10.0 20.0)")
        assert result is not None
        assert "10.0" in result
        assert "20.0" in result


class TestPointFieldValidation:
    """PointField.validate enforces null constraints and value correctness."""

    def test_null_allowed_when_null_true(self) -> None:
        field = PointField(null=True)
        field.name = "location"
        field.validate(None)  # must not raise

    def test_null_rejected_when_null_false(self) -> None:
        field = PointField(null=False)
        field.name = "location"
        with pytest.raises(ValueError, match="null"):
            field.validate(None)

    def test_valid_point_passes(self) -> None:
        field = PointField()
        field.name = "location"
        field.validate(Point(1.0, 2.0))

    def test_valid_wkt_string_passes(self) -> None:
        field = PointField()
        field.name = "location"
        field.validate("POINT(10.0 20.0)")


class TestPointFieldAttributes:
    """PointField stores srid, geography, and generates correct column type."""

    def test_default_srid(self) -> None:
        f = PointField()
        assert f.srid == 4326

    def test_custom_srid(self) -> None:
        f = PointField(srid=27700)
        assert f.srid == 27700

    def test_geometry_column_type(self) -> None:
        f = PointField(srid=4326)
        assert f.db_column_type == "GEOMETRY(Point,4326)"

    def test_geography_column_type(self) -> None:
        f = PointField(srid=4326, geography=True)
        assert f.db_column_type == "GEOGRAPHY(Point,4326)"

    def test_column_type_property(self) -> None:
        f = PointField()
        assert f._column_type == "GEOMETRY(Point,4326)"


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


class TestPostGISBackend:
    """PostGISBackend generates correct DDL and serialises values."""

    def setup_method(self) -> None:
        self.backend = PostGISBackend()
        self.field = PointField(srid=4326)

    def test_column_ddl_geometry(self) -> None:
        ddl = self.backend.column_ddl(self.field)
        assert ddl == "GEOMETRY(Point,4326)"

    def test_column_ddl_geography(self) -> None:
        field = PointField(srid=4326, geography=True)
        ddl = self.backend.column_ddl(field)
        assert ddl == "GEOGRAPHY(Point,4326)"

    def test_to_db_none_returns_none(self) -> None:
        assert self.backend.to_db(None) is None

    def test_to_db_point_returns_ewkt(self) -> None:
        p = Point(10.0, 20.0)
        result = self.backend.to_db(p)
        assert result == "SRID=4326;POINT(10.0 20.0)"

    def test_to_python_none_returns_none(self) -> None:
        assert self.backend.to_python(None) is None

    def test_to_python_point_passthrough(self) -> None:
        p = Point(1.0, 2.0)
        assert self.backend.to_python(p) is p

    def test_to_python_wkt_string(self) -> None:
        result = self.backend.to_python("POINT(10.0 20.0)", srid=4326)
        assert isinstance(result, Point)
        assert result.longitude == 10.0

    def test_to_python_ewkt_string(self) -> None:
        result = self.backend.to_python("SRID=4326;POINT(10.0 20.0)")
        assert isinstance(result, Point)


class TestFallbackTextBackend:
    """FallbackTextBackend stores WKT in TEXT and round-trips correctly."""

    def setup_method(self) -> None:
        self.backend = FallbackTextBackend()
        self.field = PointField(srid=4326)

    def test_column_ddl_is_text(self) -> None:
        assert self.backend.column_ddl(self.field) == "TEXT"

    def test_to_db_none_returns_none(self) -> None:
        assert self.backend.to_db(None) is None

    def test_to_db_point_returns_wkt(self) -> None:
        p = Point(10.0, 20.0)
        result = self.backend.to_db(p)
        assert result == "POINT(10.0 20.0)"

    def test_to_python_none_returns_none(self) -> None:
        assert self.backend.to_python(None) is None

    def test_to_python_wkt_string(self) -> None:
        result = self.backend.to_python("POINT(10.0 20.0)")
        assert isinstance(result, Point)
        assert result.longitude == 10.0


class TestGetBackend:
    """get_backend resolves the correct backend for dialect strings."""

    def test_postgresql_returns_postgis_backend(self) -> None:
        assert isinstance(get_backend("postgresql"), PostGISBackend)

    def test_postgres_alias(self) -> None:
        assert isinstance(get_backend("postgres"), PostGISBackend)

    def test_postgis_alias(self) -> None:
        assert isinstance(get_backend("postgis"), PostGISBackend)

    def test_sqlite_returns_fallback(self) -> None:
        assert isinstance(get_backend("sqlite"), FallbackTextBackend)

    def test_mysql_returns_fallback(self) -> None:
        assert isinstance(get_backend("mysql"), FallbackTextBackend)

    def test_unknown_dialect_returns_fallback(self) -> None:
        assert isinstance(get_backend("unknown_db"), FallbackTextBackend)

    def test_case_insensitive(self) -> None:
        assert isinstance(get_backend("POSTGRESQL"), PostGISBackend)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


class TestParsePoint:
    """parse_point converts diverse input formats to Point instances."""

    def test_none_returns_none(self) -> None:
        assert parse_point(None) is None

    def test_point_passthrough(self) -> None:
        p = Point(1.0, 2.0)
        assert parse_point(p) is p

    def test_tuple_input(self) -> None:
        result = parse_point((-0.1276, 51.5074))
        assert isinstance(result, Point)
        assert result.longitude == -0.1276

    def test_list_input(self) -> None:
        result = parse_point([10.0, 20.0])
        assert isinstance(result, Point)
        assert result.latitude == 20.0

    def test_wkt_string(self) -> None:
        result = parse_point("POINT(5.0 10.0)")
        assert isinstance(result, Point)
        assert result.longitude == 5.0

    def test_geojson_dict(self) -> None:
        result = parse_point({"type": "Point", "coordinates": [5.0, 10.0]})
        assert isinstance(result, Point)
        assert result.latitude == 10.0

    def test_geojson_string(self) -> None:
        gj = json.dumps({"type": "Point", "coordinates": [5.0, 10.0]})
        result = parse_point(gj)
        assert isinstance(result, Point)
        assert result.longitude == 5.0

    def test_custom_srid_propagated(self) -> None:
        result = parse_point((1.0, 2.0), srid=27700)
        assert result is not None
        assert result.srid == 27700


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TestExceptions:
    """Exception hierarchy and messages are correct."""

    def test_invalid_point_error_is_geo_location_error(self) -> None:
        with pytest.raises(GeoLocationError):
            raise InvalidPointError("bad coords")

    def test_dependency_missing_error_is_import_error(self) -> None:
        exc = _DepMissing("shapely>=2.0")
        assert isinstance(exc, ImportError)

    def test_dependency_missing_error_message_contains_package(self) -> None:
        exc = _DepMissing("shapely>=2.0")
        assert "shapely>=2.0" in str(exc)

    def test_dependency_missing_error_message_contains_install_hint(self) -> None:
        exc = _DepMissing("shapely>=2.0")
        assert "pip install openviper[Geolocation]" in str(exc)

    def test_geo_location_error_base(self) -> None:
        assert issubclass(GeoLocationError, Exception)

    def test_invalid_point_error_is_value_error(self) -> None:
        assert issubclass(InvalidPointError, ValueError)
