"""Unit tests for openviper.serializers.base — Serializer and ModelSerializer."""

from typing import Any

import pytest

from openviper.db import fields
from openviper.db.fields import ForeignKey
from openviper.db.models import Model
from openviper.exceptions import ValidationError
from openviper.serializers.base import (
    ModelSerializer,
    Serializer,
    _python_type_for_field_by_name,
    field_validator,
)

# ── Test Serializers ─────────────────────────────────────────────────────────


class SimpleSerializer(Serializer):
    name: str
    age: int


class DefaultSerializer(Serializer):
    name: str = "default"
    value: int = 0


# ── Test Model ───────────────────────────────────────────────────────────────


class FakePost(Model):
    class Meta:
        table_name = "fake_posts"

    title = fields.CharField(max_length=200)
    body = fields.TextField()
    published = fields.BooleanField(default=False)


class FakePostSerializer(ModelSerializer):
    class Meta:
        model = FakePost
        fields = "__all__"


class FakeAuthor(Model):
    class Meta:
        table_name = "fake_authors"

    username = fields.CharField(max_length=100)


class FakeComment(Model):
    class Meta:
        table_name = "fake_comments"

    author = ForeignKey(FakeAuthor)
    body = fields.TextField()


class FakeCommentSerializer(Serializer):
    author: int
    body: str


# ── Tests ────────────────────────────────────────────────────────────────────


class TestSerializerValidate:
    def test_valid_data(self):
        result = SimpleSerializer.validate({"name": "alice", "age": 30})
        assert result.name == "alice"
        assert result.age == 30

    def test_invalid_data_raises(self):
        with pytest.raises(ValidationError):
            SimpleSerializer.validate({"name": "alice"})  # Missing age

    def test_invalid_type_raises(self):
        with pytest.raises(ValidationError):
            SimpleSerializer.validate({"name": "alice", "age": "not_a_number"})


class TestSerializerSerialize:
    def test_serialize(self):
        s = SimpleSerializer(name="bob", age=25)
        data = s.serialize()
        assert data["name"] == "bob"
        assert data["age"] == 25

    def test_serialize_excludes(self):
        s = SimpleSerializer(name="bob", age=25)
        data = s.serialize(exclude={"age"})
        assert "age" not in data
        assert data["name"] == "bob"


class TestSerializerSerializeJson:
    def test_serialize_json(self):
        s = SimpleSerializer(name="eve", age=20)
        json_bytes = s.serialize_json()
        assert b"eve" in json_bytes
        assert b"20" in json_bytes


class TestSerializerValidateJsonString:
    def test_valid_json(self):
        result = SimpleSerializer.validate_json_string('{"name": "alice", "age": 30}')
        assert result.name == "alice"
        assert result.age == 30


class TestSerializerFromOrm:
    def test_from_orm(self):
        post = FakePost(title="Hello", body="World", published=True)
        s = FakePostSerializer.from_orm(post)
        assert s.title == "Hello"  # type: ignore
        assert s.body == "World"  # type: ignore


class TestSerializerFromOrmForeignKey:
    def test_fk_field_resolves_to_raw_id(self) -> None:
        comment = FakeComment(body="Nice post")
        comment.__dict__["author_id"] = 7
        s = FakeCommentSerializer.from_orm(comment)
        assert s.author == 7

    def test_fk_field_with_model_instance_resolves_to_id(self) -> None:
        author = FakeAuthor(username="alice")
        author.__dict__["id"] = 3
        comment = FakeComment(body="Hello")
        comment.author = author
        s = FakeCommentSerializer.from_orm(comment)
        assert s.author == 3

    def test_fk_field_null_resolves_to_none(self) -> None:
        comment = FakeComment(body="Orphan")
        comment.__dict__["author_id"] = None

        class NullableFKSerializer(Serializer):
            author: int | None
            body: str

        s = NullableFKSerializer.from_orm(comment)
        assert s.author is None


class TestSerializerFromOrmMany:
    def test_from_orm_many(self):
        posts = [
            FakePost(title="Post 1", body="Body 1"),
            FakePost(title="Post 2", body="Body 2"),
        ]
        results = FakePostSerializer.from_orm_many(posts)
        assert len(results) == 2
        assert results[0].title == "Post 1"  # type: ignore


class TestSerializerPartial:
    def test_partial_validation(self):
        result = SimpleSerializer.validate({"name": "alice"}, partial=True)
        assert result.name == "alice"

    def test_partial_allows_missing_fields(self):
        result = DefaultSerializer.validate({"name": "custom"}, partial=True)
        assert result.name == "custom"


class TestSerializerDefaults:
    def test_defaults_applied(self):
        result = DefaultSerializer.validate({})
        assert result.name == "default"
        assert result.value == 0


class TestFieldTypeMapping:
    def test_integer_field(self):
        assert _python_type_for_field_by_name("IntegerField") is int

    def test_char_field(self):
        assert _python_type_for_field_by_name("CharField") is str

    def test_boolean_field(self):
        assert _python_type_for_field_by_name("BooleanField") is bool

    def test_float_field(self):
        assert _python_type_for_field_by_name("FloatField") is float

    def test_foreign_key(self):
        assert _python_type_for_field_by_name("ForeignKey") is int

    def test_unknown_field_defaults_to_any(self):
        result = _python_type_for_field_by_name("UnknownField")
        assert result is Any


class TestFieldValidator:
    def test_field_validator_works(self):
        class UpperSerializer(Serializer):
            name: str

            @field_validator("name")
            @classmethod
            def validate_name(cls, v):
                return v.upper()

        s = UpperSerializer.validate({"name": "alice"})
        assert s.name == "ALICE"


class TestModelSerializer:
    def test_auto_generates_fields(self):
        s = FakePostSerializer.validate(
            {
                "title": "Test",
                "body": "Content",
                "published": True,
            }
        )
        assert s.title == "Test"  # type: ignore

    def test_serializes_back(self):
        s = FakePostSerializer.validate(
            {
                "title": "Test",
                "body": "Content",
            }
        )
        data = s.serialize()
        assert data["title"] == "Test"
