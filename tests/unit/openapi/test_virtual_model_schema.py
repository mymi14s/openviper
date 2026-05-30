"""Tests for virtual model OpenAPI schema generation."""

from __future__ import annotations

from openviper.db.fields import CharField, IntegerField
from openviper.db.models import Model
from openviper.serializers.base import ModelSerializer


class OpenAPIVirtualModel(Model):
    name = CharField(max_length=100)
    age = IntegerField(default=0)

    class Meta:
        table_name = "openapi_virtual_model"
        virtual = True
        backend = "default"


class OpenAPIVirtualModelSerializer(ModelSerializer):
    class Meta:
        model = OpenAPIVirtualModel
        fields = ["id", "name", "age"]


def test_virtual_model_serializer_generates_openapi_schema() -> None:
    schema = OpenAPIVirtualModelSerializer.model_json_schema()
    assert schema["type"] == "object"
    assert "id" in schema["properties"]
    assert "name" in schema["properties"]
    assert "age" in schema["properties"]
    assert schema["properties"]["name"]["type"] == "string"
    # IntegerField with default=0 is optional; type may be in anyOf.
    age_schema = schema["properties"]["age"]
    if "type" in age_schema:
        assert age_schema["type"] == "integer"
    else:
        types = {t.get("type") for t in age_schema.get("anyOf", []) if "type" in t}
        assert "integer" in types


def test_virtual_model_schema_matches_normal_model_schema() -> None:
    class NormalModel(Model):
        name = CharField(max_length=100)
        age = IntegerField(default=0)

        class Meta:
            table_name = "normal_openapi_model"

    class NormalModelSerializer(ModelSerializer):
        class Meta:
            model = NormalModel
            fields = ["id", "name", "age"]

    virtual_schema = OpenAPIVirtualModelSerializer.model_json_schema()
    normal_schema = NormalModelSerializer.model_json_schema()

    assert virtual_schema["properties"].keys() == normal_schema["properties"].keys()
    assert virtual_schema["type"] == normal_schema["type"]


def test_virtual_model_schema_includes_required_fields() -> None:
    schema = OpenAPIVirtualModelSerializer.model_json_schema()
    assert "required" in schema
    assert "name" in schema["required"]
    # age has default=0 so it is not required.
    assert "age" not in schema["required"]
