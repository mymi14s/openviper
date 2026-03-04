"""Integration tests for openviper.serializers (Serializer, ModelSerializer, PaginatedSerializer)."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

import pytest

from openviper.exceptions import ValidationError
from openviper.serializers.base import (
    ModelSerializer,
    PaginatedSerializer,
    Serializer,
    _field_is_optional,
    _python_type_for_field,
    field_validator,
    model_validator,
)

# ---------------------------------------------------------------------------
# Basic Serializer tests
# ---------------------------------------------------------------------------


class SimpleSerializer(Serializer):
    name: str
    age: int
    email: str = ""


class TestSerializerValidate:
    def test_valid_data_returns_instance(self):
        s = SimpleSerializer.validate({"name": "Alice", "age": 25})
        assert s.name == "Alice"
        assert s.age == 25

    def test_invalid_data_raises_validation_error(self):
        with pytest.raises(ValidationError) as exc_info:
            SimpleSerializer.validate({"name": "Alice", "age": "not_a_number"})
        err = exc_info.value
        assert err.validation_errors

    def test_missing_required_field_raises_error(self):
        with pytest.raises(ValidationError) as exc_info:
            SimpleSerializer.validate({"age": 25})
        err = exc_info.value
        assert any("name" in e["field"] for e in err.validation_errors)

    def test_extra_field_is_ignored(self):
        s = SimpleSerializer.validate({"name": "Bob", "age": 30, "unknown": "x"})
        assert s.name == "Bob"
        assert not hasattr(s, "unknown")

    def test_default_field_is_optional(self):
        s = SimpleSerializer.validate({"name": "Bob", "age": 30})
        assert s.email == ""


class TestSerializerValidateJsonString:
    def test_valid_json_returns_instance(self):
        s = SimpleSerializer.validate_json_string('{"name": "Alice", "age": 25}')
        assert s.name == "Alice"

    def test_invalid_json_raises_validation_error(self):
        with pytest.raises(ValidationError):
            SimpleSerializer.validate_json_string('{"name": "Alice", "age": "bad"}')

    def test_malformed_json_raises_validation_error(self):
        with pytest.raises(Exception):
            SimpleSerializer.validate_json_string("{not valid json")


class TestSerializerFromOrm:
    def test_from_orm_reads_attributes(self):
        class FakeObj:
            name = "Test"
            age = 42
            email = "t@test.com"

        s = SimpleSerializer.from_orm(FakeObj())
        assert s.name == "Test"
        assert s.age == 42

    def test_from_orm_many_creates_list(self):
        class FakeObj:
            def __init__(self, n, a):
                self.name = n
                self.age = a
                self.email = ""

        result = SimpleSerializer.from_orm_many([FakeObj("A", 1), FakeObj("B", 2)])
        assert len(result) == 2
        assert result[0].name == "A"
        assert result[1].name == "B"


class TestSerializerSerialize:
    def test_serialize_returns_dict(self):
        s = SimpleSerializer.validate({"name": "Alice", "age": 25})
        data = s.serialize()
        assert isinstance(data, dict)
        assert data["name"] == "Alice"
        assert data["age"] == 25

    def test_serialize_excludes_fields(self):
        s = SimpleSerializer.validate({"name": "Alice", "age": 25})
        data = s.serialize(exclude={"age"})
        assert "age" not in data
        assert "name" in data

    def test_serialize_many_creates_list(self):
        class FakeObj:
            name = "X"
            age = 1
            email = ""

        result = SimpleSerializer.serialize_many([FakeObj(), FakeObj()])
        assert isinstance(result, list)
        assert len(result) == 2

    def test_write_only_fields_excluded_from_serialize(self):
        class SecretSerializer(Serializer):
            username: str
            password: str
            write_only_fields = ("password",)

        s = SecretSerializer.validate({"username": "alice", "password": "secret"})
        data = s.serialize()
        assert "username" in data
        assert "password" not in data


# ---------------------------------------------------------------------------
# Field validator decorator
# ---------------------------------------------------------------------------


class TestFieldValidator:
    def test_field_validator_transforms_value(self):
        class UpperSerializer(Serializer):
            name: str

            @field_validator("name")
            @classmethod
            def upper_name(cls, v: str) -> str:
                return v.upper()

        s = UpperSerializer.validate({"name": "alice"})
        assert s.name == "ALICE"

    def test_field_validator_rejects_invalid_value(self):
        class AgeSerializer(Serializer):
            age: int

            @field_validator("age")
            @classmethod
            def positive_age(cls, v: int) -> int:
                if v < 0:
                    raise ValueError("Age must be positive")
                return v

        with pytest.raises(ValidationError):
            AgeSerializer.validate({"age": -1})


# ---------------------------------------------------------------------------
# Model validator decorator
# ---------------------------------------------------------------------------


class TestModelValidator:
    def test_model_validator_cross_field_check(self):
        class PwdSerializer(Serializer):
            password: str
            confirm: str

            @model_validator(mode="after")
            def passwords_match(self) -> "PwdSerializer":
                if self.password != self.confirm:
                    raise ValueError("Passwords do not match")
                return self

        s = PwdSerializer.validate({"password": "abc", "confirm": "abc"})
        assert s.password == "abc"

        with pytest.raises(ValidationError):
            PwdSerializer.validate({"password": "abc", "confirm": "xyz"})


# ---------------------------------------------------------------------------
# PaginatedSerializer
# ---------------------------------------------------------------------------


class TestPaginatedSerializer:
    def test_paginated_response_structure(self):
        result = PaginatedSerializer(
            count=10,
            results=[{"id": 1}, {"id": 2}],
            next=None,
            previous=None,
        )
        assert result.count == 10
        assert len(result.results) == 2
        assert result.next is None

    def test_paginated_serializes_to_dict(self):
        p = PaginatedSerializer(count=5, results=[{"x": 1}], next=None, previous=None)
        data = p.model_dump()
        assert "results" in data
        assert "count" in data
        assert data["count"] == 5

    def test_paginated_with_pagination_links(self):
        p = PaginatedSerializer(
            count=100,
            results=[],
            next="http://example.com/api/?page=2",
            previous=None,
        )
        assert p.next == "http://example.com/api/?page=2"
        assert p.previous is None


# ---------------------------------------------------------------------------
# ModelSerializer auto-field generation
# ---------------------------------------------------------------------------


def test_model_serializer_with_auth_role():
    """ModelSerializer auto-generates fields from Role model."""
    from openviper.auth.models import Role

    class RoleSerializer(ModelSerializer):
        class Meta:
            model = Role
            fields = "__all__"

    # Should have auto-generated id, name, description, created_at
    assert "name" in RoleSerializer.model_fields
    assert "id" in RoleSerializer.model_fields


def test_model_serializer_with_exclude():
    """ModelSerializer respects Meta.exclude."""
    from openviper.auth.models import Role

    class RoleSerializer(ModelSerializer):
        class Meta:
            model = Role
            fields = "__all__"
            exclude = ("description",)

    assert "name" in RoleSerializer.model_fields
    assert "description" not in RoleSerializer.model_fields


def test_model_serializer_with_specific_fields():
    """ModelSerializer respects Meta.fields list."""
    from openviper.auth.models import Role

    class RoleSerializer(ModelSerializer):
        class Meta:
            model = Role
            fields = ["name"]

    assert "name" in RoleSerializer.model_fields
    assert "id" not in RoleSerializer.model_fields


def test_model_serializer_validate_creates_instance():
    """ModelSerializer.validate parses data correctly."""
    from openviper.auth.models import Role

    class RoleSerializer(ModelSerializer):
        class Meta:
            model = Role
            fields = ["name", "description"]

    s = RoleSerializer.validate({"name": "editor", "description": "Can edit"})
    assert s.name == "editor"


def test_model_serializer_read_only_fields():
    """ModelSerializer.read_only_fields are excluded from writes."""
    from openviper.auth.models import Role

    class RoleSerializer(ModelSerializer):
        read_only_fields = ("id",)

        class Meta:
            model = Role
            fields = "__all__"

    assert RoleSerializer.read_only_fields == ("id",)


def test_model_serializer_from_orm():
    """ModelSerializer.from_orm reads from object attributes."""
    from openviper.auth.models import Role

    class RoleSerializer(ModelSerializer):
        class Meta:
            model = Role
            fields = ["name", "description"]

    role = Role(name="admin", description="Administrator")
    s = RoleSerializer.from_orm(role)
    assert s.name == "admin"


def test_model_serializer_serialize():
    """ModelSerializer.serialize returns JSON-safe dict."""
    from openviper.auth.models import Role

    class RoleSerializer(ModelSerializer):
        class Meta:
            model = Role
            fields = ["name", "description"]

    role = Role(name="viewer", description="Read-only access")
    data = RoleSerializer.from_orm(role).serialize()
    assert data["name"] == "viewer"
    assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# _python_type_for_field and _field_is_optional helpers
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    def test_python_type_for_known_field(self):
        from openviper.db import fields

        char_field = fields.CharField(max_length=100)
        result = _python_type_for_field(char_field)
        assert result is str

    def test_python_type_for_int_field(self):
        from openviper.db import fields

        int_field = fields.IntegerField()
        result = _python_type_for_field(int_field)
        assert result is int

    def test_python_type_for_unknown_field(self):
        class UnknownField:
            pass

        result = _python_type_for_field(UnknownField())
        # Should return Any for unknown types
        assert result is Any

    def test_field_is_optional_primary_key(self):
        from openviper.db import fields

        pk_field = fields.AutoField()
        assert _field_is_optional(pk_field) is True

    def test_field_is_optional_null_field(self):
        from openviper.db import fields

        null_field = fields.CharField(max_length=50, null=True)
        assert _field_is_optional(null_field) is True

    def test_field_is_not_optional(self):
        from openviper.db import fields

        required_field = fields.CharField(max_length=50)
        assert _field_is_optional(required_field) is False

    def test_field_with_auto_now_is_optional(self):
        from openviper.db import fields

        f = fields.DateTimeField(auto_now_add=True)
        assert _field_is_optional(f) is True


# ---------------------------------------------------------------------------
# Serializer with complex field types
# ---------------------------------------------------------------------------


class TestComplexFieldTypes:
    def test_datetime_field_in_serializer(self):
        class EventSerializer(Serializer):
            title: str
            created_at: datetime.datetime | None = None

        now = datetime.datetime.now()
        s = EventSerializer.validate({"title": "Meeting", "created_at": now})
        assert s.title == "Meeting"

    def test_uuid_field_in_serializer(self):
        class ItemSerializer(Serializer):
            uid: uuid.UUID

        uid = uuid.uuid4()
        s = ItemSerializer.validate({"uid": str(uid)})
        assert s.uid == uid

    def test_decimal_field_in_serializer(self):
        class PriceSerializer(Serializer):
            price: Decimal

        s = PriceSerializer.validate({"price": "9.99"})
        assert s.price == Decimal("9.99")
