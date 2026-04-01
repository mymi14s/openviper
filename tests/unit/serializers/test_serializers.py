"""Unit tests for openviper/serializers/base.py."""

from __future__ import annotations

from typing import Any

import pytest

from openviper.exceptions import ValidationError
from openviper.serializers.base import (
    PaginatedSerializer,
    Serializer,
    field_validator,
)
from tests.factories import MockQuerySet, SimpleModel

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


class UserSerializer(Serializer):
    id: int
    username: str
    email: str = ""


class PartialUserSerializer(Serializer):
    username: str
    age: int = 0


class ValidatedSerializer(Serializer):
    name: str
    email: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if len(v) < 2:
            raise ValueError("Name too short")
        return v.lower()


class WriteOnlySerializer(Serializer):
    username: str
    password: str
    writeonly_fields = ("password",)


def make_user_data(**overrides) -> dict[str, Any]:
    base = {"id": 1, "username": "alice", "email": "alice@example.com"}
    base.update(overrides)
    return base


def make_user_obj(**overrides) -> SimpleModel:
    return SimpleModel(**make_user_data(**overrides))


# ---------------------------------------------------------------------------
# Serializer.validate
# ---------------------------------------------------------------------------


class TestSerializerValidate:
    def test_valid_data(self):
        s = UserSerializer.validate(make_user_data())
        assert s.username == "alice"

    def test_invalid_data_raises_validation_error(self):
        with pytest.raises(ValidationError):
            UserSerializer.validate({"id": "not_int", "username": "alice"})

    def test_partial_allows_missing_required_fields(self):
        s = UserSerializer.validate({"id": 1}, partial=True)
        assert s.id == 1
        assert s.username is None

    def test_field_validator_called(self):
        s = ValidatedSerializer.validate({"name": "Alice", "email": "a@b.com"})
        assert s.name == "alice"

    def test_field_validator_failure(self):
        with pytest.raises(ValidationError) as exc_info:
            ValidatedSerializer.validate({"name": "A", "email": "a@b.com"})
        assert exc_info.value.status_code == 422

    def test_validate_json_string(self):
        s = UserSerializer.validate_json_string('{"id": 1, "username": "bob"}')
        assert s.username == "bob"

    def test_validate_json_string_invalid_raises(self):
        with pytest.raises(ValidationError):
            UserSerializer.validate_json_string('{"id": "not_int"}')


# ---------------------------------------------------------------------------
# from_orm / from_orm_many
# ---------------------------------------------------------------------------


class TestFromORM:
    def test_from_orm(self):
        obj = make_user_obj()
        s = UserSerializer.from_orm(obj)
        assert s.id == 1
        assert s.username == "alice"

    def test_from_orm_many(self):
        objs = [make_user_obj(id=i, username=f"user{i}") for i in range(3)]
        instances = UserSerializer.from_orm_many(objs)
        assert len(instances) == 3
        assert instances[0].id == 0


# ---------------------------------------------------------------------------
# serialize / serialize_json
# ---------------------------------------------------------------------------


class TestSerialize:
    def test_serialize_returns_dict(self):
        s = UserSerializer.validate(make_user_data())
        d = s.serialize()
        assert isinstance(d, dict)
        assert d["username"] == "alice"

    def test_serialize_excludes_write_only(self):
        s = WriteOnlySerializer.validate({"username": "bob", "password": "secret"})
        d = s.serialize()
        assert "password" not in d
        assert "username" in d

    def test_serialize_with_explicit_exclude(self):
        s = UserSerializer.validate(make_user_data())
        d = s.serialize(exclude={"email"})
        assert "email" not in d

    def test_serialize_json_returns_bytes(self):
        s = UserSerializer.validate(make_user_data())
        data = s.serialize_json()
        assert isinstance(data, bytes)
        assert b"alice" in data


# ---------------------------------------------------------------------------
# serialize_many (async)
# ---------------------------------------------------------------------------


class TestSerializeMany:
    @pytest.mark.asyncio
    async def test_list_of_objects(self):
        objs = [make_user_obj(id=i, username=f"u{i}") for i in range(5)]
        results = await UserSerializer.serialize_many(objs)
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_queryset_with_batch(self):
        objs = [make_user_obj(id=i, username=f"u{i}") for i in range(10)]
        qs = MockQuerySet(objs)
        results = await UserSerializer.serialize_many(qs)
        assert len(results) == 10

    @pytest.mark.asyncio
    async def test_serialize_many_json_returns_bytes(self):
        objs = [make_user_obj(id=1, username="x")]
        result = await UserSerializer.serialize_many_json(objs)
        assert isinstance(result, bytes)
        assert result.startswith(b"[")


# ---------------------------------------------------------------------------
# paginate (async)
# ---------------------------------------------------------------------------


class TestPaginate:
    @pytest.mark.asyncio
    async def test_paginates_correctly(self):
        objs = [make_user_obj(id=i, username=f"u{i}") for i in range(20)]
        qs = MockQuerySet(objs)
        page = await UserSerializer.paginate(qs, page=1, page_size=5)
        assert page.count == 20
        assert len(page.results) == 5

    @pytest.mark.asyncio
    async def test_next_url_generated(self):
        objs = [make_user_obj(id=i, username=f"u{i}") for i in range(10)]
        qs = MockQuerySet(objs)
        page = await UserSerializer.paginate(qs, page=1, page_size=5, base_url="/api/users")
        assert page.next is not None
        assert "page=2" in page.next

    @pytest.mark.asyncio
    async def test_prev_url_on_second_page(self):
        objs = [make_user_obj(id=i, username=f"u{i}") for i in range(20)]
        qs = MockQuerySet(objs)
        page = await UserSerializer.paginate(qs, page=2, page_size=5, base_url="/api/users")
        assert page.previous is not None
        assert "page=1" in page.previous

    @pytest.mark.asyncio
    async def test_no_next_on_last_page(self):
        objs = [make_user_obj(id=i, username=f"u{i}") for i in range(5)]
        qs = MockQuerySet(objs)
        page = await UserSerializer.paginate(qs, page=1, page_size=5, base_url="/api")
        assert page.next is None


# ---------------------------------------------------------------------------
# PaginatedSerializer
# ---------------------------------------------------------------------------


class TestPaginatedSerializer:
    def test_fields(self):
        p = PaginatedSerializer(count=100, next="/page=2", previous=None, results=[])
        assert p.count == 100
        assert p.next == "/page=2"
        assert p.previous is None


# ---------------------------------------------------------------------------
# _build_partial_class caching
# ---------------------------------------------------------------------------


class TestPartialClassCache:
    def test_same_class_returned_on_repeat_calls(self):
        cls1 = UserSerializer._build_partial_class()
        cls2 = UserSerializer._build_partial_class()
        assert cls1 is cls2
