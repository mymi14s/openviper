import datetime
import datetime as dt_module
from decimal import Decimal

import pytest

from openviper.db.fields import (
    BooleanField,
    CharField,
    DateTimeField,
    DecimalField,
    EmailField,
    Field,
    IntegerField,
    PositiveIntegerField,
)


def test_field_base_validation():
    field = Field(null=False)
    field.name = "test"
    with pytest.raises(ValueError, match="cannot be null"):
        field.validate(None)

    field_null = Field(null=True)
    field_null.name = "test"
    field_null.validate(None)  # Should not raise


def test_char_field_max_length():
    field = CharField(max_length=5)
    field.name = "test"
    field.validate("12345")
    with pytest.raises(ValueError, match="exceeds max_length"):
        field.validate("123456")


def test_integer_field_coercion():
    field = IntegerField()
    assert field.to_python("10") == 10
    assert field.to_db("20") == 20


def test_boolean_field_coercion():
    field = BooleanField()
    assert field.to_python("true") is True
    assert field.to_python("0") is False
    assert field.to_db(True) == 1
    assert field.to_db(False) == 0


def test_datetime_field_coercion():
    field = DateTimeField()
    dt = datetime.datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt_module.UTC)
    assert field.to_python(dt.isoformat()) == dt
    assert field.to_db(dt) == dt


def test_decimal_field_coercion():
    field = DecimalField()
    assert field.to_python("10.50") == Decimal("10.50")


def test_email_field_validation():
    field = EmailField()
    field.name = "email"
    field.validate("test@example.com")
    with pytest.raises(ValueError, match="invalid email address"):
        field.validate("invalid-email")


def test_positive_integer_field_validation():
    field = PositiveIntegerField()
    field.name = "pos"
    field.validate(0)
    field.validate(10)
    with pytest.raises(ValueError, match="must be >= 0"):
        field.validate(-1)
