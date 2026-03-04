import json
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from openviper.admin.fields import (
    _serialize_default,
    coerce_field_value,
    get_field_component_type,
    get_field_schema,
    get_field_widget_config,
)
from openviper.db.fields import (
    AutoField,
    BooleanField,
    CharField,
    DateField,
    DateTimeField,
    DecimalField,
    FloatField,
    ForeignKey,
    IntegerField,
    JSONField,
    PositiveIntegerField,
    TextField,
    TimeField,
    UUIDField,
)


def test_get_field_component_type():
    assert get_field_component_type(AutoField()) == "hidden"
    assert get_field_component_type(CharField()) == "text"
    assert get_field_component_type(IntegerField()) == "number"

    class UnknownField:
        pass

    assert get_field_component_type(UnknownField()) == "text"


def test_get_field_widget_config():
    # Common config
    char_field = CharField(max_length=50, null=False, blank=False, help_text="help")
    config = get_field_widget_config(char_field)
    assert config["required"] is True
    assert config["readonly"] is False
    assert config["help_text"] == "help"
    assert config["max_length"] == 50

    # Choices
    choice_field = CharField(choices=[("a", "A"), ("b", "B")])
    config_choices = get_field_widget_config(choice_field)
    assert config_choices["choices"] == [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}]

    # Integer/Float/Decimal
    assert get_field_widget_config(PositiveIntegerField())["min"] == 0
    assert get_field_widget_config(FloatField())["step"] == 0.01
    assert get_field_widget_config(DecimalField(decimal_places=3))["step"] == 0.001

    # Text
    assert get_field_widget_config(TextField())["rows"] == 5

    # DateTime
    dt_field = DateTimeField(auto_now_add=True)
    dt_config = get_field_widget_config(dt_field)
    assert dt_config["auto_now_add"] is True
    assert dt_config["readonly"] is True

    # UUID
    assert get_field_widget_config(UUIDField())["readonly"] is True


def test_get_field_schema():
    field = CharField(max_length=100, unique=True, default="Hello")
    field.name = "title"  # explicit name set
    field._column_type = "VARCHAR(100)"

    schema = get_field_schema(field)
    assert schema["name"] == "title"
    assert schema["type"] == "CharField"
    assert schema["component"] == "text"
    assert schema["column_type"] == "VARCHAR(100)"
    assert schema["unique"] is True
    assert schema["default"] == "Hello"
    assert schema["config"]["max_length"] == 100

    # Test ForeignKey with string reference
    # Test valid module
    fk = ForeignKey("openviper.auth.models.User")
    schema_fk = get_field_schema(fk)
    assert "auth/User" in schema_fk.get("related_model", "")

    # Test invalid module fallback
    fk2 = ForeignKey("invalid_module.BadModel")
    schema_fk2 = get_field_schema(fk2)
    assert schema_fk2["related_model"] == "invalid_module/BadModel"

    # Test with actual class
    class FakeModel:
        __name__ = "FakeModel"
        _app_name = "fake_app"

    fk3 = ForeignKey(FakeModel)
    schema_fk3 = get_field_schema(fk3)
    assert schema_fk3["related_model"] == "fake_app/FakeModel"

    # Test string reference with only 1 part
    fk4 = ForeignKey("User")
    schema_fk4 = get_field_schema(fk4)
    assert schema_fk4["related_model"] == "default/User"


def test_serialize_default():
    assert _serialize_default(None) is None
    assert _serialize_default("test") == "test"
    assert _serialize_default(123) == 123
    assert _serialize_default({"a": 1}) == {"a": 1}

    def my_callable():
        return 1

    assert _serialize_default(my_callable) == "__callable__"

    class CustomObj:
        def __str__(self):
            return "custom"

    assert _serialize_default(CustomObj()) == "custom"


def test_coerce_field_value():
    assert coerce_field_value(CharField(), None) is None

    # Ints
    assert coerce_field_value(IntegerField(), "123") == 123

    # Floats / Decimals
    assert coerce_field_value(FloatField(), "12.3") == 12.3
    assert coerce_field_value(DecimalField(), "12.3") == Decimal("12.3")

    # Bools
    assert coerce_field_value(BooleanField(), True) is True
    assert coerce_field_value(BooleanField(), "true") is True
    assert coerce_field_value(BooleanField(), "1") is True
    assert coerce_field_value(BooleanField(), "false") is False

    # Dates / Times
    assert coerce_field_value(DateField(), "2023-01-01") == date(2023, 1, 1)
    assert coerce_field_value(DateField(), date(2023, 1, 1)) == date(2023, 1, 1)

    assert coerce_field_value(DateTimeField(), "2023-01-01T12:00:00Z") == datetime.fromisoformat(
        "2023-01-01T12:00:00+00:00"
    )
    assert coerce_field_value(TimeField(), "12:30:00") == time(12, 30)

    # JSON
    assert coerce_field_value(JSONField(), '{"a": 1}') == {"a": 1}
    assert coerce_field_value(JSONField(), {"a": 1}) == {"a": 1}

    # UUID
    u = uuid.uuid4()
    assert coerce_field_value(UUIDField(), str(u)) == u

    # Default fallback
    assert coerce_field_value(CharField(), "text") == "text"
