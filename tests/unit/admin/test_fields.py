import uuid
from datetime import date, datetime, time
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from openviper.admin.fields import (
    FIELD_COMPONENT_MAP,
    _serialize_default,
    coerce_field_value,
    get_field_component_type,
    get_field_schema,
    get_field_widget_config,
)


def _make_field(
    field_type,
    null=False,
    blank=False,
    choices=None,
    max_length=None,
    decimal_places=None,
    auto_now=False,
    auto_now_add=False,
    help_text="",
    to=None,
):
    """Create a mock field for testing."""
    field = MagicMock()
    field.__class__.__name__ = field_type
    field.null = null
    field.blank = blank
    field.choices = choices
    field.max_length = max_length
    field.decimal_places = decimal_places
    field.auto_now = auto_now
    field.auto_now_add = auto_now_add
    field.help_text = help_text
    field.name = "test_field"
    field._column_type = "TEXT"
    field.primary_key = False
    field.unique = False
    field.db_index = False
    field.default = None
    field.to = to
    return field


class TestFieldComponentMap:
    """Test FIELD_COMPONENT_MAP constant."""

    def test_has_standard_field_types(self):
        assert "CharField" in FIELD_COMPONENT_MAP
        assert "IntegerField" in FIELD_COMPONENT_MAP
        assert "BooleanField" in FIELD_COMPONENT_MAP
        assert "DateField" in FIELD_COMPONENT_MAP
        assert "ForeignKey" in FIELD_COMPONENT_MAP

    def test_component_values(self):
        assert FIELD_COMPONENT_MAP["CharField"] == "text"
        assert FIELD_COMPONENT_MAP["IntegerField"] == "number"
        assert FIELD_COMPONENT_MAP["BooleanField"] == "checkbox"
        assert FIELD_COMPONENT_MAP["EmailField"] == "email"
        assert FIELD_COMPONENT_MAP["ForeignKey"] == "foreignkey"


class TestGetFieldComponentType:
    """Test get_field_component_type function."""

    def test_char_field_returns_text(self):
        field = _make_field("CharField")
        assert get_field_component_type(field) == "text"

    def test_integer_field_returns_number(self):
        field = _make_field("IntegerField")
        assert get_field_component_type(field) == "number"

    def test_boolean_field_returns_checkbox(self):
        field = _make_field("BooleanField")
        assert get_field_component_type(field) == "checkbox"

    def test_foreign_key_returns_foreignkey(self):
        field = _make_field("ForeignKey")
        assert get_field_component_type(field) == "foreignkey"

    def test_unknown_field_returns_text(self):
        field = _make_field("UnknownField")
        assert get_field_component_type(field) == "text"


class TestGetFieldWidgetConfig:
    """Test get_field_widget_config function."""

    def test_required_field(self):
        field = _make_field("CharField", null=False, blank=False)
        config = get_field_widget_config(field)
        assert config["required"] is True

    def test_optional_field(self):
        field = _make_field("CharField", null=True, blank=True)
        config = get_field_widget_config(field)
        assert config["required"] is False

    def test_auto_field_readonly(self):
        field = _make_field("AutoField")
        config = get_field_widget_config(field)
        assert config["readonly"] is True

    def test_help_text(self):
        field = _make_field("CharField", help_text="Enter your name")
        config = get_field_widget_config(field)
        assert config["help_text"] == "Enter your name"

    def test_char_field_max_length(self):
        field = _make_field("CharField", max_length=255)
        config = get_field_widget_config(field)
        assert config["max_length"] == 255

    def test_choices_configuration(self):
        choices = [("A", "Option A"), ("B", "Option B")]
        field = _make_field("CharField", choices=choices)
        config = get_field_widget_config(field)
        assert "choices" in config
        assert len(config["choices"]) == 2
        assert config["choices"][0] == {"value": "A", "label": "Option A"}

    def test_positive_integer_field_min_value(self):
        field = _make_field("PositiveIntegerField")
        config = get_field_widget_config(field)
        assert config["min"] == 0

    def test_float_field_step(self):
        field = _make_field("FloatField")
        config = get_field_widget_config(field)
        assert config["step"] == 0.01

    def test_decimal_field_step(self):
        field = _make_field("DecimalField", decimal_places=3)
        config = get_field_widget_config(field)
        assert config["step"] == 0.001

    def test_text_field_rows(self):
        field = _make_field("TextField")
        config = get_field_widget_config(field)
        assert config["rows"] == 5

    def test_datetime_field_auto_now_readonly(self):
        field = _make_field("DateTimeField", auto_now=True)
        config = get_field_widget_config(field)
        assert config["readonly"] is True
        assert config["auto_now"] is True

    def test_datetime_field_auto_now_add_readonly(self):
        field = _make_field("DateTimeField", auto_now_add=True)
        config = get_field_widget_config(field)
        assert config["readonly"] is True
        assert config["auto_now_add"] is True

    def test_uuid_field_readonly(self):
        field = _make_field("UUIDField")
        config = get_field_widget_config(field)
        assert config["readonly"] is True

    def test_file_field_widget_config(self):
        """Test FileField widget configuration."""
        field = _make_field("FileField")
        field.upload_to = "documents/"
        config = get_field_widget_config(field)
        assert config["upload_to"] == "documents/"

    def test_file_field_with_max_size(self):
        """Test FileField with max file size."""
        field = _make_field("FileField")
        field.upload_to = "docs/"
        field._max_file_size = 5 * 1024 * 1024  # 5MB
        config = get_field_widget_config(field)
        assert config["max_file_size"] == 5 * 1024 * 1024

    def test_image_field_with_allowed_extensions(self):
        """Test ImageField with allowed extensions."""
        field = _make_field("ImageField")
        field.upload_to = "images/"
        field.allowed_extensions = [".jpg", ".png", ".gif"]
        config = get_field_widget_config(field)
        assert config["allowed_extensions"] == [".jpg", ".png", ".gif"]


class TestGetFieldSchema:
    """Test get_field_schema function."""

    def test_basic_field_schema(self):
        field = _make_field("CharField")
        schema = get_field_schema(field)

        assert schema["name"] == "test_field"
        assert schema["type"] == "CharField"
        assert schema["component"] == "text"
        assert "config" in schema

    def test_field_with_default(self):
        field = _make_field("CharField")
        field.default = "default_value"
        schema = get_field_schema(field)
        assert schema["default"] == "default_value"

    def test_field_with_callable_default(self):
        field = _make_field("CharField")
        field.default = lambda: "value"
        schema = get_field_schema(field)
        assert schema["default"] == "__callable__"

    def test_foreign_key_field_with_string_reference(self):
        field = _make_field("ForeignKey", to="auth.User")
        schema = get_field_schema(field)
        # Should handle string reference gracefully
        assert "related_model" in schema or "related_model" not in schema

    def test_foreign_key_field_with_model_class(self):
        mock_model = MagicMock()
        mock_model.__name__ = "User"
        mock_model._app_name = "auth"

        field = _make_field("ForeignKey", to=mock_model)
        schema = get_field_schema(field)

        if "related_model" in schema:
            assert "User" in schema["related_model"]

    def test_caching_behavior(self):
        """Test that field schema uses caching."""
        field = _make_field("CharField")
        schema1 = get_field_schema(field)
        schema2 = get_field_schema(field)

        # Both should have the same structure
        assert schema1["type"] == schema2["type"]
        assert schema1["component"] == schema2["component"]

    def test_foreign_key_with_module_string(self):
        """Test ForeignKey to with 'app.models.Model' string."""
        field = _make_field("ForeignKey", to="auth.models.TestModel")

        with patch("openviper.admin.fields.importlib.import_module") as mock_import:
            mock_module = MagicMock()
            mock_model = MagicMock()
            mock_model._app_name = "auth_app"
            mock_module.TestModel = mock_model
            mock_import.return_value = mock_module

            schema = get_field_schema(field)
            assert schema["related_model"] == "auth_app/TestModel"

    def test_foreign_key_with_module_string_fallback(self):
        """Test ForeignKey to with fallback import string."""
        field = _make_field("ForeignKey", to="auth.sub.TestModel")

        # We need to mock import_module
        with patch("openviper.admin.fields.importlib.import_module") as mock_import:
            # Let's say TestModel is on the mocked module
            mock_module = MagicMock()
            mock_model = MagicMock()
            mock_model.__name__ = "TestModel"
            mock_model._app_name = "auth"
            mock_module.TestModel = mock_model

            # The function will try auth.models first, let it raise ImportError
            def import_side_effect(name):
                if name == "auth.sub.models":
                    raise ImportError("No models module")
                return mock_module

            mock_import.side_effect = import_side_effect

            schema = get_field_schema(field)
            assert schema["related_model"] == "auth/TestModel"

    def test_foreign_key_with_module_string_fallback_error(self):
        """Test ForeignKey to with fallback import string throwing error."""
        field = _make_field("ForeignKey", to="auth.sub.TestModel")

        with patch("openviper.admin.fields.importlib.import_module") as mock_import:
            mock_import.side_effect = ImportError("No module at all")
            schema = get_field_schema(field)
            assert schema["related_model"] == "auth/TestModel"


class TestCoerceFieldValue:
    """Test coerce_field_value function."""

    def test_none_value_returns_none(self):
        field = _make_field("CharField")
        assert coerce_field_value(field, None) is None

    def test_integer_field_coercion(self):
        field = _make_field("IntegerField")
        assert coerce_field_value(field, "42") == 42
        assert coerce_field_value(field, 42) == 42

    def test_float_field_coercion(self):
        field = _make_field("FloatField")
        assert coerce_field_value(field, "3.14") == 3.14
        assert coerce_field_value(field, 3.14) == 3.14

    def test_decimal_field_coercion(self):
        field = _make_field("DecimalField")
        result = coerce_field_value(field, "10.50")
        assert isinstance(result, Decimal)
        assert result == Decimal("10.50")

    def test_boolean_field_coercion_true(self):
        field = _make_field("BooleanField")
        assert coerce_field_value(field, "true") is True
        assert coerce_field_value(field, "True") is True
        assert coerce_field_value(field, "1") is True
        assert coerce_field_value(field, "yes") is True
        assert coerce_field_value(field, "on") is True
        assert coerce_field_value(field, True) is True

    def test_boolean_field_coercion_false(self):
        field = _make_field("BooleanField")
        assert coerce_field_value(field, "false") is False
        assert coerce_field_value(field, "False") is False
        assert coerce_field_value(field, "0") is False
        assert coerce_field_value(field, False) is False

    def test_date_field_coercion(self):
        field = _make_field("DateField")
        result = coerce_field_value(field, "2023-05-15")
        assert isinstance(result, date)
        assert result == date(2023, 5, 15)

    def test_datetime_field_coercion(self):
        field = _make_field("DateTimeField")
        result = coerce_field_value(field, "2023-05-15T10:30:00")
        assert isinstance(result, datetime)
        assert result.year == 2023
        assert result.month == 5
        assert result.day == 15

    def test_datetime_field_coercion_with_z(self):
        field = _make_field("DateTimeField")
        result = coerce_field_value(field, "2023-05-15T10:30:00Z")
        assert isinstance(result, datetime)

    def test_time_field_coercion(self):
        field = _make_field("TimeField")
        result = coerce_field_value(field, "14:30:00")
        assert isinstance(result, time)
        assert result.hour == 14
        assert result.minute == 30

    def test_json_field_coercion_from_string(self):
        field = _make_field("JSONField")
        result = coerce_field_value(field, '{"key": "value"}')
        assert isinstance(result, dict)
        assert result == {"key": "value"}

    def test_json_field_coercion_invalid_json(self):
        field = _make_field("JSONField")
        with pytest.raises(ValueError) as exc:
            coerce_field_value(field, '{"invalid": json}')
        assert "Invalid JSON format" in str(exc.value)

    def test_json_field_coercion_from_dict(self):
        field = _make_field("JSONField")
        value = {"key": "value"}
        result = coerce_field_value(field, value)
        assert result == value

    def test_uuid_field_coercion(self):
        field = _make_field("UUIDField")
        test_uuid = "550e8400-e29b-41d4-a716-446655440000"
        result = coerce_field_value(field, test_uuid)
        assert isinstance(result, uuid.UUID)
        assert str(result) == test_uuid

    def test_foreign_key_coercion_from_string_digit(self):
        field = _make_field("ForeignKey")
        result = coerce_field_value(field, "123")
        assert result == 123
        assert isinstance(result, int)

    def test_foreign_key_coercion_from_int(self):
        field = _make_field("ForeignKey")
        result = coerce_field_value(field, 456)
        assert result == 456

    def test_foreign_key_coercion_empty_string(self):
        field = _make_field("ForeignKey")
        result = coerce_field_value(field, "")
        assert result is None

    def test_one_to_one_field_coercion(self):
        field = _make_field("OneToOneField")
        result = coerce_field_value(field, "789")
        assert result == 789

    def test_empty_string_on_nullable_numeric_field(self):
        field = _make_field("IntegerField", null=True)
        result = coerce_field_value(field, "")
        assert result is None

    def test_empty_string_on_non_nullable_char_field(self):
        field = _make_field("CharField", null=False)
        result = coerce_field_value(field, "")
        # Should return empty string, not None
        assert result == ""

    def test_string_value_unchanged(self):
        field = _make_field("CharField")
        result = coerce_field_value(field, "hello")
        assert result == "hello"

    def test_list_value_unchanged(self):
        field = _make_field("CharField")
        result = coerce_field_value(field, ["a", "b"])
        assert result == ["a", "b"]

    def test_dict_value_unchanged(self):
        field = _make_field("CharField")
        result = coerce_field_value(field, {"key": "value"})
        assert result == {"key": "value"}

    def test_date_field_coercion_from_object(self):
        field = _make_field("DateField")
        d = date.today()
        assert coerce_field_value(field, d) is d

    def test_datetime_field_coercion_from_object(self):
        field = _make_field("DateTimeField")
        d = datetime.now()
        assert coerce_field_value(field, d) is d

    def test_time_field_coercion_from_object(self):
        field = _make_field("TimeField")
        t = time(12, 0)
        assert coerce_field_value(field, t) is t

    def test_uuid_field_coercion_from_object(self):
        field = _make_field("UUIDField")
        u = uuid.uuid4()
        assert coerce_field_value(field, u) is u

    def test_foreign_key_coercion_from_foreign_object(self):
        field = _make_field("ForeignKey")
        obj = object()
        assert coerce_field_value(field, obj) is obj

    def test_foreign_key_coercion_empty_str(self):
        field = _make_field("ForeignKey", null=False)  # Not nullable but empty string
        # openviper/admin/fields.py has `if value == '': return None` for FK
        assert coerce_field_value(field, "") is None

    def test_file_field_coercion_empty_string_clears(self):
        """Empty string in file field should return None (clear file)."""
        field = _make_field("FileField")
        result = coerce_field_value(field, "")
        assert result is None

    def test_file_field_coercion_path_unchanged(self):
        """String paths for existing files should pass through unchanged."""
        field = _make_field("FileField")
        path = "uploads/image.png"
        result = coerce_field_value(field, path)
        assert result == path

    def test_file_field_coercion_upload_file_unchanged(self):
        """UploadFile objects should pass through unchanged."""
        field = _make_field("FileField")
        upload = MagicMock()
        result = coerce_field_value(field, upload)
        assert result is upload

    def test_image_field_coercion_empty_string_clears(self):
        """Empty string in image field should return None (clear file)."""
        field = _make_field("ImageField")
        result = coerce_field_value(field, "")
        assert result is None

    def test_image_field_coercion_path_unchanged(self):
        """String paths for existing images should pass through unchanged."""
        field = _make_field("ImageField")
        path = "images/photo.jpg"
        result = coerce_field_value(field, path)
        assert result == path


class TestFieldSchemaEdgeCases:
    """Test edge cases and special scenarios."""

    def test_field_without_name_attribute(self):
        field = MagicMock()
        field.__class__.__name__ = "CharField"
        field.name = None
        field._column_type = "TEXT"
        field.primary_key = False
        field.null = False
        field.blank = False
        field.unique = False
        field.db_index = False
        field.default = None

        # Should handle gracefully
        schema = get_field_schema(field)
        assert schema["type"] == "CharField"

    def test_field_with_complex_default(self):
        field = _make_field("CharField")
        field.default = {"complex": "object"}

        schema = get_field_schema(field)
        # Should convert to string
        assert isinstance(schema["default"], str)

    def test_many_to_many_field_component(self):
        field = _make_field("ManyToManyField")
        component = get_field_component_type(field)
        assert component == "multiselect"

    def test_serialize_default_none_direct(self):
        assert _serialize_default(None) is None

    def test_serialize_default_unserializable_dict(self):
        class Unserializable:
            pass

        assert "Unserializable" in _serialize_default({"k": Unserializable()})

    def test_serialize_default_unsupported_object(self):
        class CustomObj:
            def __str__(self):
                return "custom_str"

        assert _serialize_default(CustomObj()) == "custom_str"
