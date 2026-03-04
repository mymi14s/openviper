"""Integration tests for openviper.db.fields (Field types, validation, conversion)."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest

from openviper.db import fields

# ---------------------------------------------------------------------------
# Field base class
# ---------------------------------------------------------------------------


class TestFieldBase:
    def test_field_null_validation_raises(self):
        f = fields.CharField(max_length=50)
        f.name = "username"
        with pytest.raises(ValueError, match="cannot be null"):
            f.validate(None)

    def test_field_null_allowed(self):
        f = fields.CharField(max_length=50, null=True)
        f.name = "username"
        f.validate(None)  # Should not raise

    def test_field_choices_validation_passes(self):
        f = fields.CharField(max_length=10, choices=[("admin", "Admin"), ("user", "User")])
        f.name = "role"
        f.validate("admin")  # Should not raise

    def test_field_choices_validation_fails(self):
        f = fields.CharField(max_length=10, choices=[("admin", "Admin"), ("user", "User")])
        f.name = "role"
        with pytest.raises(ValueError, match="not in choices"):
            f.validate("superuser")

    def test_field_repr(self):
        f = fields.CharField(max_length=50)
        f.name = "testfield"
        assert "CharField" in repr(f)
        assert "testfield" in repr(f)

    def test_column_name_uses_db_column_if_set(self):
        f = fields.CharField(max_length=50, db_column="my_custom_col")
        f.name = "username"
        assert f.column_name == "my_custom_col"

    def test_column_name_defaults_to_name(self):
        f = fields.CharField(max_length=50)
        f.name = "username"
        assert f.column_name == "username"


# ---------------------------------------------------------------------------
# AutoField
# ---------------------------------------------------------------------------


class TestAutoField:
    def test_to_python_int_conversion(self):
        f = fields.AutoField()
        assert f.to_python("42") == 42
        assert f.to_python(5) == 5

    def test_to_python_none(self):
        f = fields.AutoField()
        assert f.to_python(None) is None

    def test_auto_field_is_primary_key(self):
        f = fields.AutoField()
        assert f.primary_key is True


# ---------------------------------------------------------------------------
# IntegerField
# ---------------------------------------------------------------------------


class TestIntegerField:
    def test_to_python(self):
        f = fields.IntegerField()
        assert f.to_python("42") == 42

    def test_to_python_none(self):
        f = fields.IntegerField()
        assert f.to_python(None) is None

    def test_to_db(self):
        f = fields.IntegerField()
        assert f.to_db("10") == 10
        assert f.to_db(None) is None


# ---------------------------------------------------------------------------
# FloatField
# ---------------------------------------------------------------------------


class TestFloatField:
    def test_to_python(self):
        f = fields.FloatField()
        assert f.to_python("3.14") == pytest.approx(3.14)

    def test_to_python_none(self):
        f = fields.FloatField()
        assert f.to_python(None) is None


# ---------------------------------------------------------------------------
# DecimalField
# ---------------------------------------------------------------------------


class TestDecimalField:
    def test_to_python(self):
        f = fields.DecimalField()
        result = f.to_python("9.99")
        assert result == Decimal("9.99")

    def test_to_python_float(self):
        f = fields.DecimalField()
        result = f.to_python(3.14)
        assert isinstance(result, Decimal)

    def test_to_python_none(self):
        f = fields.DecimalField()
        assert f.to_python(None) is None


# ---------------------------------------------------------------------------
# CharField
# ---------------------------------------------------------------------------


class TestCharField:
    def test_to_python(self):
        f = fields.CharField(max_length=100)
        assert f.to_python("hello") == "hello"
        assert f.to_python(42) == "42"

    def test_to_python_none(self):
        f = fields.CharField(max_length=100)
        assert f.to_python(None) is None

    def test_validate_passes_within_max_length(self):
        f = fields.CharField(max_length=5)
        f.name = "code"
        f.validate("hello")  # exactly 5 chars, OK

    def test_validate_fails_over_max_length(self):
        f = fields.CharField(max_length=5)
        f.name = "code"
        with pytest.raises(ValueError, match="exceeds max_length"):
            f.validate("toolong")

    def test_validate_unicode_length(self):
        f = fields.CharField(max_length=3)
        f.name = "emoji_field"
        # Unicode characters each count as 1
        f.validate("abc")  # OK
        with pytest.raises(ValueError):
            f.validate("abcd")


# ---------------------------------------------------------------------------
# TextField
# ---------------------------------------------------------------------------


class TestTextField:
    def test_to_python(self):
        f = fields.TextField()
        assert f.to_python("long text") == "long text"

    def test_to_python_none(self):
        f = fields.TextField()
        assert f.to_python(None) is None


# ---------------------------------------------------------------------------
# BooleanField
# ---------------------------------------------------------------------------


class TestBooleanField:
    def test_to_python_true_variations(self):
        f = fields.BooleanField()
        for truthy in ("1", "true", "yes", "on", "True", "YES", "ON"):
            assert f.to_python(truthy) is True, f"Expected True for {truthy!r}"

    def test_to_python_false_variations(self):
        f = fields.BooleanField()
        for falsy in ("0", "false", "no", "off", ""):
            assert f.to_python(falsy) is False, f"Expected False for {falsy!r}"

    def test_to_python_actual_bool(self):
        f = fields.BooleanField()
        assert f.to_python(True) is True
        assert f.to_python(False) is False

    def test_to_python_none(self):
        f = fields.BooleanField()
        assert f.to_python(None) is None

    def test_to_db_true(self):
        f = fields.BooleanField()
        assert f.to_db(True) == 1

    def test_to_db_false(self):
        f = fields.BooleanField()
        assert f.to_db(False) == 0

    def test_to_db_none(self):
        f = fields.BooleanField()
        assert f.to_db(None) is None


# ---------------------------------------------------------------------------
# DateTimeField
# ---------------------------------------------------------------------------


class TestDateTimeField:
    def test_to_python_none(self):
        f = fields.DateTimeField()
        assert f.to_python(None) is None

    def test_to_python_datetime_passthrough(self):
        f = fields.DateTimeField()
        dt = datetime.datetime(2023, 1, 15, 12, 0, 0)
        result = f.to_python(dt)
        assert isinstance(result, datetime.datetime)

    def test_to_python_from_isoformat_string(self):
        f = fields.DateTimeField()
        result = f.to_python("2023-01-15T12:00:00")
        assert isinstance(result, datetime.datetime)

    def test_to_db_none(self):
        f = fields.DateTimeField()
        assert f.to_db(None) is None

    def test_to_db_from_string(self):
        f = fields.DateTimeField()
        result = f.to_db("2023-01-15T12:00:00")
        assert isinstance(result, datetime.datetime)


# ---------------------------------------------------------------------------
# DateField
# ---------------------------------------------------------------------------


class TestDateField:
    def test_to_python_none(self):
        f = fields.DateField()
        assert f.to_python(None) is None

    def test_to_python_date_passthrough(self):
        f = fields.DateField()
        d = datetime.date(2023, 5, 15)
        assert f.to_python(d) == d

    def test_to_python_from_string(self):
        f = fields.DateField()
        result = f.to_python("2023-05-15")
        assert result == datetime.date(2023, 5, 15)


# ---------------------------------------------------------------------------
# TimeField
# ---------------------------------------------------------------------------


class TestTimeField:
    def test_to_python_none(self):
        f = fields.TimeField()
        assert f.to_python(None) is None

    def test_to_python_time_passthrough(self):
        f = fields.TimeField()
        t = datetime.time(10, 30, 0)
        assert f.to_python(t) == t

    def test_to_python_from_string(self):
        f = fields.TimeField()
        result = f.to_python("10:30:00")
        assert result == datetime.time(10, 30, 0)


# ---------------------------------------------------------------------------
# BinaryField
# ---------------------------------------------------------------------------


class TestBinaryField:
    def test_to_python_bytes(self):
        f = fields.BinaryField()
        assert f.to_python(b"data") == b"data"

    def test_to_python_str(self):
        f = fields.BinaryField()
        assert f.to_python("hello") == b"hello"

    def test_to_python_none(self):
        f = fields.BinaryField()
        assert f.to_python(None) is None

    def test_to_db_same_as_to_python(self):
        f = fields.BinaryField()
        assert f.to_db(b"test") == b"test"


# ---------------------------------------------------------------------------
# UUIDField
# ---------------------------------------------------------------------------


class TestUUIDField:
    def test_to_python_uuid_passthrough(self):
        f = fields.UUIDField()
        uid = uuid.uuid4()
        assert f.to_python(uid) == uid

    def test_to_python_from_string(self):
        f = fields.UUIDField()
        uid_str = "12345678-1234-5678-1234-567812345678"
        result = f.to_python(uid_str)
        assert isinstance(result, uuid.UUID)

    def test_to_python_none(self):
        f = fields.UUIDField()
        assert f.to_python(None) is None

    def test_to_db_converts_to_string(self):
        f = fields.UUIDField()
        uid = uuid.uuid4()
        result = f.to_db(uid)
        assert isinstance(result, str)

    def test_to_db_none(self):
        f = fields.UUIDField()
        assert f.to_db(None) is None

    def test_auto_uuid_field_has_default(self):
        f = fields.UUIDField(auto=True)
        assert callable(f.default)


# ---------------------------------------------------------------------------
# JSONField
# ---------------------------------------------------------------------------


class TestJSONField:
    def test_to_python_dict(self):
        # JSON stored as string
        import json

        f = fields.JSONField()
        data = json.dumps({"key": "value"})
        result = f.to_python(data)
        assert result == {"key": "value"}

    def test_to_python_none(self):
        f = fields.JSONField()
        assert f.to_python(None) is None

    def test_to_python_dict_passthrough(self):
        f = fields.JSONField()
        d = {"already": "parsed"}
        result = f.to_python(d)
        assert result == d

    def test_to_db_dict_to_string(self):
        import json

        f = fields.JSONField()
        data = {"key": "value"}
        result = f.to_db(data)
        assert isinstance(result, str)
        assert json.loads(result) == data

    def test_to_db_none(self):
        f = fields.JSONField()
        assert f.to_db(None) is None
