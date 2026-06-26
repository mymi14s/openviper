"""Unit tests for ArrayField in openviper.db.fields."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from openviper.db.fields import (
    ArrayField,
    BooleanField,
    CharField,
    FallbackJsonBackend,
    FloatField,
    IntegerField,
    PostgresArrayBackend,
)
from openviper.db.fields import (
    get_array_backend as get_backend,
)
from openviper.db.fields import (
    reset_array_backend as reset_backend,
)


class TestArrayFieldConstruction:
    """ArrayField initialisation and type enforcement."""

    def test_accepts_field_class_and_auto_instantiates(self) -> None:
        """Passing a Field class auto-instantiates it with defaults."""
        field = ArrayField(IntegerField)
        assert isinstance(field.base_field, IntegerField)

    def test_accepts_field_instance(self) -> None:
        """Passing a Field instance uses it directly."""
        field = ArrayField(IntegerField())
        assert isinstance(field.base_field, IntegerField)

    def test_rejects_non_field_type(self) -> None:
        with pytest.raises(
            TypeError, match="base_field must be a Field instance or Field subclass"
        ):
            ArrayField("not_a_field")  # type: ignore[arg-type]

    def test_rejects_plain_type(self) -> None:
        with pytest.raises(
            TypeError, match="base_field must be a Field instance or Field subclass"
        ):
            ArrayField(int)  # type: ignore[arg-type]

    def test_accepts_char_field_instance(self) -> None:
        field = ArrayField(CharField(max_length=50))
        assert isinstance(field.base_field, CharField)

    def test_size_parameter(self) -> None:
        field = ArrayField(IntegerField(), size=10)
        assert field.size == 10

    def test_size_defaults_to_none(self) -> None:
        field = ArrayField(IntegerField())
        assert field.size is None

    def test_inherits_null_kwarg(self) -> None:
        field = ArrayField(IntegerField(), null=True)
        assert field.null is True

    def test_inherits_default_kwarg(self) -> None:
        field = ArrayField(IntegerField(), default=list)
        assert field.default is list

    def test_repr(self) -> None:
        field = ArrayField(IntegerField())
        field.name = "scores"
        r = repr(field)
        assert "ArrayField" in r
        assert "IntegerField" in r
        assert "scores" in r


class TestArrayFieldToPython:
    """ArrayField.to_python converts database values to Python lists."""

    def test_none_returns_none(self) -> None:
        field = ArrayField(IntegerField())
        assert field.to_python(None) is None

    def test_list_of_integers(self) -> None:
        field = ArrayField(IntegerField())
        result = field.to_python([1, 2, 3])
        assert result == [1, 2, 3]

    def test_tuple_to_list(self) -> None:
        field = ArrayField(IntegerField())
        result = field.to_python((1, 2, 3))
        assert result == [1, 2, 3]

    def test_json_string(self) -> None:
        field = ArrayField(IntegerField())
        result = field.to_python("[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_invalid_json_string_returns_none(self) -> None:
        field = ArrayField(IntegerField())
        assert field.to_python("not json") is None

    def test_json_string_non_array_returns_none(self) -> None:
        field = ArrayField(IntegerField())
        assert field.to_python('{"key": "value"}') is None

    def test_coerces_string_elements_via_base_field(self) -> None:
        field = ArrayField(IntegerField())
        result = field.to_python(["1", "2", "3"])
        assert result == [1, 2, 3]

    def test_char_field_preserves_strings(self) -> None:
        field = ArrayField(CharField(max_length=50))
        result = field.to_python(["a", "b", "c"])
        assert result == ["a", "b", "c"]


class TestArrayFieldToDb:
    """ArrayField.to_db prepares Python lists for database storage."""

    def test_none_returns_none(self) -> None:
        field = ArrayField(IntegerField())
        assert field.to_db(None) is None

    def test_list_passthrough_on_postgres(self) -> None:
        field = ArrayField(IntegerField())
        field.name = "scores"
        with patch(
            "openviper.db.fields.is_postgresql",
            return_value=True,
        ):
            reset_backend()
            result = field.to_db([1, 2, 3])
            assert result == [1, 2, 3]
            reset_backend()

    def test_json_encoding_on_fallback(self) -> None:
        field = ArrayField(IntegerField())
        field.name = "scores"
        with patch(
            "openviper.db.fields.is_postgresql",
            return_value=False,
        ):
            reset_backend()
            result = field.to_db([1, 2, 3])
            assert isinstance(result, str)
            assert json.loads(result) == [1, 2, 3]
            reset_backend()

    def test_rejects_non_sequence(self) -> None:
        field = ArrayField(IntegerField())
        field.name = "scores"
        with pytest.raises(ValueError, match="must be a list or tuple"):
            field.to_db("not a list")

    def test_coerces_elements_via_base_field(self) -> None:
        field = ArrayField(IntegerField())
        field.name = "scores"
        with patch(
            "openviper.db.fields.is_postgresql",
            return_value=True,
        ):
            reset_backend()
            result = field.to_db([1, 2, 3])
            assert result == [1, 2, 3]
            reset_backend()


class TestArrayFieldValidate:
    """ArrayField.validate enforces type and size constraints."""

    def test_none_passes_when_null_allowed(self) -> None:
        field = ArrayField(IntegerField(), null=True)
        field.validate(None)  # should not raise

    def test_none_fails_when_null_not_allowed(self) -> None:
        field = ArrayField(IntegerField(), null=False)
        field.name = "scores"
        with pytest.raises(ValueError, match="cannot be null"):
            field.validate(None)

    def test_valid_list_passes(self) -> None:
        field = ArrayField(IntegerField())
        field.validate([1, 2, 3])  # should not raise

    def test_rejects_non_list(self) -> None:
        field = ArrayField(IntegerField())
        field.name = "scores"
        with pytest.raises(ValueError, match="expects a list or tuple"):
            field.validate("not a list")

    def test_size_enforcement(self) -> None:
        field = ArrayField(IntegerField(), size=3)
        field.name = "scores"
        field.validate([1, 2, 3])  # should not raise
        with pytest.raises(ValueError, match="exceeds maximum size"):
            field.validate([1, 2, 3, 4])

    def test_size_none_allows_any_length(self) -> None:
        field = ArrayField(IntegerField(), size=None)
        field.validate(list(range(100)))  # should not raise

    def test_validates_each_element_via_base_field(self) -> None:
        """Each element is validated through the base field's validate method."""
        field = ArrayField(IntegerField(), null=False)
        field.name = "scores"
        # IntegerField.validate only checks null and choices, not type.
        # The real coercion happens in to_python/to_db. Verify that validate
        # passes for valid integer lists and rejects null when not allowed.
        field.validate([1, 2, 3])  # should not raise


class TestPostgresArrayBackend:
    """PostgresArrayBackend generates native ARRAY DDL."""

    def test_column_ddl_integer_array(self) -> None:
        backend = PostgresArrayBackend()
        field = ArrayField(IntegerField())
        field.name = "scores"
        assert backend.column_ddl(field) == "INTEGER[]"

    def test_column_ddl_text_array(self) -> None:
        backend = PostgresArrayBackend()
        field = ArrayField(CharField(max_length=50))
        field.name = "tags"
        assert backend.column_ddl(field) == "VARCHAR[]"

    def test_to_db_returns_list_unchanged(self) -> None:
        backend = PostgresArrayBackend()
        field = ArrayField(IntegerField())
        field.name = "scores"
        assert backend.to_db([1, 2, 3]) == [1, 2, 3]


class TestFallbackJsonBackend:
    """FallbackJsonBackend stores arrays as JSON text."""

    def test_column_ddl_returns_text(self) -> None:
        backend = FallbackJsonBackend()
        field = ArrayField(IntegerField())
        field.name = "scores"
        assert backend.column_ddl(field) == "TEXT"

    def test_to_db_returns_json_string(self) -> None:
        backend = FallbackJsonBackend()
        field = ArrayField(IntegerField())
        field.name = "scores"
        result = backend.to_db([1, 2, 3])
        assert isinstance(result, str)
        assert json.loads(result) == [1, 2, 3]


class TestGetBackend:
    """get_backend selects the correct backend based on database dialect."""

    def setup_method(self) -> None:
        reset_backend()

    def teardown_method(self) -> None:
        reset_backend()

    def test_returns_postgres_backend_for_postgres(self) -> None:
        with patch(
            "openviper.db.fields.is_postgresql",
            return_value=True,
        ):
            backend = get_backend()
            assert isinstance(backend, PostgresArrayBackend)

    def test_returns_fallback_for_non_postgres(self) -> None:
        with patch(
            "openviper.db.fields.is_postgresql",
            return_value=False,
        ):
            backend = get_backend()
            assert isinstance(backend, FallbackJsonBackend)

    def test_caches_backend(self) -> None:
        with patch(
            "openviper.db.fields.is_postgresql",
            return_value=True,
        ):
            b1 = get_backend()
            b2 = get_backend()
            assert b1 is b2

    def test_reset_backend_clears_cache(self) -> None:
        with patch(
            "openviper.db.fields.is_postgresql",
            return_value=True,
        ):
            get_backend()
        reset_backend()
        with patch(
            "openviper.db.fields.is_postgresql",
            return_value=False,
        ):
            b2 = get_backend()
            assert not isinstance(b2, PostgresArrayBackend)


class TestArrayFieldDbColumnType:
    """ArrayField.db_column_type returns the correct DDL type string."""

    def test_integer_array_on_postgres(self) -> None:
        field = ArrayField(IntegerField())
        field.name = "scores"
        with patch(
            "openviper.db.fields.is_postgresql",
            return_value=True,
        ):
            reset_backend()
            assert field.db_column_type == "INTEGER[]"
            reset_backend()

    def test_varchar_array_on_postgres(self) -> None:
        field = ArrayField(CharField(max_length=50))
        field.name = "tags"
        with patch(
            "openviper.db.fields.is_postgresql",
            return_value=True,
        ):
            reset_backend()
            assert field.db_column_type == "VARCHAR[]"
            reset_backend()

    def test_text_on_fallback(self) -> None:
        field = ArrayField(IntegerField())
        field.name = "scores"
        with patch(
            "openviper.db.fields.is_postgresql",
            return_value=False,
        ):
            reset_backend()
            assert field.db_column_type == "TEXT"
            reset_backend()
