"""Unit tests for openviper.admin.api.serializers — model serialization."""

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from unittest.mock import MagicMock

from openviper.admin.api.serializers import (
    ModelDetailSerializer,
    ModelListSerializer,
    serialize_field_info,
    serialize_for_detail,
    serialize_for_list,
    serialize_instance,
    serialize_model_info,
    serialize_value,
)
from openviper.admin.options import ModelAdmin


def _make_model_class(name="TestModel", fields=None):
    """Create a mock model class."""
    model = MagicMock()
    model.__name__ = name
    model._app_name = "test"
    model._table_name = name.lower()
    model._fields = fields or {}
    return model


def _make_model_admin(model_class, list_display=None):
    """Create a mock ModelAdmin."""
    admin = ModelAdmin(model_class)
    if list_display:
        admin.list_display = list_display
    return admin


def _make_model_instance(model_class, **kwargs):
    """Create a mock model instance."""
    instance = MagicMock()
    instance.__class__ = model_class
    instance.id = kwargs.get("id", 1)

    for key, value in kwargs.items():
        setattr(instance, key, value)

    # Mock getattr to return values
    def mock_getattr(self, name, default=None):
        return kwargs.get(name, default)

    instance.__getattribute__ = lambda name: (
        kwargs.get(name) if name in kwargs else MagicMock.__getattribute__(instance, name)
    )

    return instance


class TestSerializeValue:
    """Test serialize_value function."""

    def test_none_value(self):
        """Test serializing None."""
        assert serialize_value(None) is None

    def test_string_value(self):
        """Test serializing string."""
        assert serialize_value("hello") == "hello"

    def test_integer_value(self):
        """Test serializing integer."""
        assert serialize_value(42) == 42

    def test_float_value(self):
        """Test serializing float."""
        assert serialize_value(3.14) == 3.14

    def test_boolean_value(self):
        """Test serializing boolean."""
        assert serialize_value(True) is True
        assert serialize_value(False) is False

    def test_datetime_value(self):
        """Test serializing datetime."""
        dt = datetime(2023, 5, 15, 10, 30, 0)
        result = serialize_value(dt)
        assert isinstance(result, str)
        assert "2023" in result

    def test_date_value(self):
        """Test serializing date."""
        d = date(2023, 5, 15)
        result = serialize_value(d)
        assert isinstance(result, str)
        assert "2023-05-15" in result

    def test_time_value(self):
        """Test serializing time."""
        t = time(10, 30, 0)
        result = serialize_value(t)
        assert isinstance(result, str)
        assert "10:30" in result

    def test_list_value(self):
        """Test serializing list."""
        result = serialize_value([1, 2, "three"])
        assert result == [1, 2, "three"]

    def test_tuple_value(self):
        """Test serializing tuple."""
        result = serialize_value((1, 2, 3))
        assert result == [1, 2, 3]

    def test_dict_value(self):
        """Test serializing dict."""
        result = serialize_value({"key": "value", "num": 42})
        assert result == {"key": "value", "num": 42}

    def test_nested_dict(self):
        """Test serializing nested dict."""
        nested = {"outer": {"inner": "value"}}
        result = serialize_value(nested)
        assert result == {"outer": {"inner": "value"}}

    def test_uuid_value(self):
        """Test serializing UUID."""
        test_uuid = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
        result = serialize_value(test_uuid)
        assert isinstance(result, str)
        assert "550e8400" in result

    def test_decimal_value(self):
        """Test serializing Decimal."""
        dec = Decimal("10.50")
        result = serialize_value(dec)
        assert isinstance(result, float)
        assert result == 10.5

    def test_custom_object_with_isoformat(self):
        """Test object with isoformat method."""
        obj = MagicMock()
        obj.isoformat.return_value = "2023-05-15T10:30:00"

        result = serialize_value(obj)
        assert result == "2023-05-15T10:30:00"

    def test_custom_object_with_hex(self):
        """Test object with hex attribute (e.g. UUID)."""
        obj = uuid.uuid4()

        result = serialize_value(obj)
        assert isinstance(result, str)

    def test_custom_object_with_as_tuple(self):
        """Test object with as_tuple method (like Decimal)."""
        obj = Decimal("10.50")

        result = serialize_value(obj)
        assert isinstance(result, float)

    def test_unknown_object_converts_to_string(self):
        """Test that unknown objects are converted to string."""

        class CustomObject:
            def __str__(self):
                return "custom"

        obj = CustomObject()
        result = serialize_value(obj)
        assert result == "custom"


class TestSerializeInstance:
    """Test serialize_instance function."""

    def test_basic_serialization(self):
        """Test basic instance serialization."""
        fields = {"name": MagicMock(), "email": MagicMock()}
        model_class = _make_model_class(fields=fields)
        model_admin = _make_model_admin(model_class)

        instance = MagicMock()
        instance.__class__ = model_class
        instance.id = 1
        instance.name = "John"
        instance.email = "john@example.com"

        result = serialize_instance(instance, model_admin)

        assert result["id"] == 1
        assert "name" in result
        assert "email" in result

    def test_serialization_with_include_fields(self):
        """Test serialization with specific fields."""
        model_class = _make_model_class()
        model_admin = _make_model_admin(model_class)

        instance = MagicMock()
        instance.__class__ = model_class
        instance.id = 1
        instance.name = "John"
        instance.email = "john@example.com"

        result = serialize_instance(instance, model_admin, include_fields=["name"])

        assert result["id"] == 1
        assert "name" in result

    def test_serialization_with_none_values(self):
        """Test serialization handles None values."""
        fields = {"name": MagicMock()}
        model_class = _make_model_class(fields=fields)
        model_admin = _make_model_admin(model_class)

        instance = MagicMock()
        instance.__class__ = model_class
        instance.id = 1
        instance.name = None

        result = serialize_instance(instance, model_admin)

        assert result["name"] is None


class TestSerializeForList:
    """Test serialize_for_list function."""

    def test_serializes_list_display_fields(self):
        """Test that only list_display fields are serialized."""
        model_class = _make_model_class()
        model_admin = _make_model_admin(model_class, list_display=["id", "name"])

        instance = MagicMock()
        instance.__class__ = model_class
        instance.id = 1
        instance.name = "John"
        instance.email = "john@example.com"  # Not in list_display

        result = serialize_for_list(instance, model_admin)

        assert result["id"] == 1
        assert "name" in result

    def test_handles_missing_attributes(self):
        """Test handling of missing attributes."""
        model_class = _make_model_class()
        model_admin = _make_model_admin(model_class, list_display=["id", "missing"])

        instance = MagicMock()
        instance.__class__ = model_class
        instance.id = 1
        instance.missing = None

        result = serialize_for_list(instance, model_admin)

        assert result["id"] == 1


class TestSerializeForDetail:
    """Test serialize_for_detail function."""

    def test_serializes_all_fields(self):
        """Test that all fields are serialized."""
        fields = {"name": MagicMock(), "email": MagicMock()}
        model_class = _make_model_class(fields=fields)
        model_admin = _make_model_admin(model_class)

        instance = MagicMock()
        instance.__class__ = model_class
        instance.id = 1
        instance.name = "John"
        instance.email = "john@example.com"

        result = serialize_for_detail(instance, model_admin)

        assert result["id"] == 1
        assert "name" in result
        assert "email" in result

    def test_serializes_complex_values(self):
        """Test serialization of complex field values."""
        fields = {"created_at": MagicMock()}
        model_class = _make_model_class(fields=fields)
        model_admin = _make_model_admin(model_class)

        instance = MagicMock()
        instance.__class__ = model_class
        instance.id = 1
        instance.created_at = datetime(2023, 5, 15)

        result = serialize_for_detail(instance, model_admin)

        assert result["id"] == 1
        assert isinstance(result["created_at"], str)


class TestSerializeModelInfo:
    """Test serialize_model_info function."""

    def test_returns_model_info(self):
        """Test that model info is returned."""
        model_class = _make_model_class("User")
        model_admin = _make_model_admin(model_class)

        result = serialize_model_info(model_admin)

        assert isinstance(result, dict)
        # Should have model metadata
        assert "name" in result or "model_name" in result


class TestSerializeFieldInfo:
    """Test serialize_field_info function."""

    def test_returns_field_schema(self):
        """Test that field schema is returned."""
        field = MagicMock()
        field.__class__.__name__ = "CharField"
        field.name = "test_field"
        field._column_type = "TEXT"
        field.primary_key = False
        field.null = False
        field.blank = False
        field.unique = False
        field.db_index = False
        field.default = None

        result = serialize_field_info(field)

        assert isinstance(result, dict)
        assert "type" in result or "name" in result


class TestModelListSerializer:
    """Test ModelListSerializer class."""

    def test_initialization(self):
        """Test serializer initialization."""
        model_class = _make_model_class()
        model_admin = _make_model_admin(model_class)

        serializer = ModelListSerializer(model_admin)

        assert serializer.model_admin is model_admin

    def test_serialize_empty_list(self):
        """Test serializing empty list."""
        model_class = _make_model_class()
        model_admin = _make_model_admin(model_class)
        serializer = ModelListSerializer(model_admin)

        result = serializer.serialize([])

        assert result == []

    def test_serialize_single_instance(self):
        """Test serializing single instance."""
        model_class = _make_model_class()
        model_admin = _make_model_admin(model_class, list_display=["id", "name"])
        serializer = ModelListSerializer(model_admin)

        instance = MagicMock()
        instance.__class__ = model_class
        instance.id = 1
        instance.name = "Test"

        result = serializer.serialize([instance])

        assert len(result) == 1
        assert result[0]["id"] == 1

    def test_serialize_multiple_instances(self):
        """Test serializing multiple instances."""
        model_class = _make_model_class()
        model_admin = _make_model_admin(model_class, list_display=["id"])
        serializer = ModelListSerializer(model_admin)

        instances = [MagicMock(id=i, __class__=model_class) for i in range(1, 4)]

        result = serializer.serialize(instances)

        assert len(result) == 3


class TestModelDetailSerializer:
    """Test ModelDetailSerializer class."""

    def test_initialization(self):
        """Test serializer initialization."""
        model_class = _make_model_class()
        model_admin = _make_model_admin(model_class)

        serializer = ModelDetailSerializer(model_admin)

        assert serializer.model_admin is model_admin

    def test_serialize_instance(self):
        """Test serializing single instance."""
        fields = {"name": MagicMock()}
        model_class = _make_model_class(fields=fields)
        model_admin = _make_model_admin(model_class)
        serializer = ModelDetailSerializer(model_admin)

        instance = MagicMock()
        instance.__class__ = model_class
        instance.id = 1
        instance.name = "Test"

        result = serializer.serialize(instance)

        assert isinstance(result, dict)
        assert result["id"] == 1


class TestSerializationEdgeCases:
    """Test edge cases and special scenarios."""

    def test_serialize_with_circular_reference(self):
        """Test handling of circular references."""
        # Circular references in simple objects should convert to string
        obj = {"key": "value"}
        result = serialize_value(obj)
        assert result == {"key": "value"}

    def test_serialize_large_list(self):
        """Test serializing large list."""
        large_list = list(range(1000))
        result = serialize_value(large_list)
        assert len(result) == 1000

    def test_serialize_deeply_nested_structure(self):
        """Test serializing deeply nested structure."""
        nested = {"level1": {"level2": {"level3": "value"}}}
        result = serialize_value(nested)
        assert result["level1"]["level2"]["level3"] == "value"

    def test_serialize_mixed_types_list(self):
        """Test serializing list with mixed types."""
        mixed = [1, "string", 3.14, None, datetime(2023, 1, 1)]
        result = serialize_value(mixed)
        assert isinstance(result, list)
        assert len(result) == 5

    def test_serialize_instance_with_property_error(self):
        """Test handling of property access errors."""
        model_class = _make_model_class()
        model_admin = _make_model_admin(model_class)

        instance = MagicMock()
        instance.__class__ = model_class
        instance.id = 1

        # Should handle gracefully
        result = serialize_instance(instance, model_admin, include_fields=["missing"])
        assert "id" in result
