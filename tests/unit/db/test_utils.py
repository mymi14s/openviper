"""Unit tests for openviper.db.utils — cast_to_pk_type."""

from __future__ import annotations

from unittest.mock import MagicMock

from openviper.db.utils import cast_to_pk_type

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_model(pk_type=int, has_pk=True, to_python_raises=False):
    """Return a minimal mock model class for cast_to_pk_type."""
    model = MagicMock()
    if has_pk:
        pk_field = MagicMock()
        pk_field.primary_key = True
        if to_python_raises:
            pk_field.to_python.side_effect = ValueError("cannot cast")
        else:
            pk_field.to_python.side_effect = lambda v: pk_type(v)
        model._fields = {"id": pk_field}
    else:
        model._fields = {}  # no primary key field
    return model


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCastToPkType:
    def test_none_value_returns_none(self):
        """cast_to_pk_type(model, None) returns None immediately (line 22)."""
        model = _make_model()
        result = cast_to_pk_type(model, None)
        assert result is None

    def test_int_pk_casts_string_to_int(self):
        """String value is cast to int when PK field has to_python."""
        model = _make_model(pk_type=int)
        result = cast_to_pk_type(model, "42")
        assert result == 42
        assert isinstance(result, int)

    def test_to_python_exception_returns_original_value(self):
        """ValueError from to_python falls back to original value (lines 35-37)."""
        model = _make_model(to_python_raises=True)
        result = cast_to_pk_type(model, "bad_id")
        assert result == "bad_id"

    def test_no_pk_field_returns_original_value(self):
        """No primary_key=True field → original value returned (line 39)."""
        model = _make_model(has_pk=False)
        result = cast_to_pk_type(model, "99")
        assert result == "99"

    def test_pk_field_without_to_python_returns_original_value(self):
        """PK field without to_python attribute → original value returned (line 39)."""
        model = MagicMock()
        pk_field = MagicMock(spec=["primary_key"])  # no to_python method
        pk_field.primary_key = True
        model._fields = {"id": pk_field}
        result = cast_to_pk_type(model, "77")
        assert result == "77"

    def test_no_fields_attribute_returns_original_value(self):
        """Model without _fields attribute → original value returned."""
        model = MagicMock(spec=[])  # no _fields
        result = cast_to_pk_type(model, "55")
        assert result == "55"
