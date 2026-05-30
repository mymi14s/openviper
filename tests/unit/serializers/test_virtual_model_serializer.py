"""Tests for virtual model serializer compatibility."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError as PydanticValidationError

from openviper.db.backends.base import VirtualBackend, VirtualBackendCapabilities
from openviper.db.backends.registry import backend_registry
from openviper.db.fields import CharField, IntegerField
from openviper.db.models import Model
from openviper.serializers.base import ModelSerializer

if TYPE_CHECKING:
    from openviper.db.queryspec import QuerySpec


class InMemoryVirtualBackend(VirtualBackend):
    """Fake backend for serializer tests."""

    def __init__(
        self,
        rows: Sequence[Mapping[str, object]] | None = None,
        capabilities: VirtualBackendCapabilities | None = None,
    ) -> None:
        self.rows = [dict(row) for row in rows or []]
        self.capabilities = capabilities or VirtualBackendCapabilities()

    async def get(
        self,
        model_class: type[Model],
        primary_key: object,
    ) -> Mapping[str, object] | None:
        for row in self.rows:
            if row.get("id") == primary_key:
                return row
        return None

    async def list(
        self,
        model_class: type[Model],
        query: QuerySpec,
    ) -> Sequence[Mapping[str, object]]:
        rows = [
            row
            for row in self.rows
            if all(row.get(key) == value for key, value in query.filters.items())
        ]
        if query.order_by:
            for field_name in reversed(query.order_by):
                reverse = field_name.startswith("-")
                key = field_name[1:] if reverse else field_name
                rows.sort(key=lambda row: row.get(key), reverse=reverse)
        if query.offset is not None:
            rows = rows[query.offset :]
        if query.limit is not None:
            rows = rows[: query.limit]
        return rows

    async def create(
        self,
        model_class: type[Model],
        data: Mapping[str, object],
    ) -> Mapping[str, object]:
        row = dict(data)
        row["id"] = row.get("id") or len(self.rows) + 1
        self.rows.append(row)
        return row

    async def update(
        self,
        model_class: type[Model],
        primary_key: object,
        data: Mapping[str, object],
    ) -> Mapping[str, object]:
        for row in self.rows:
            if row.get("id") == primary_key:
                row.update(data)
                return row
        return {"id": primary_key, **data}

    async def delete(
        self,
        model_class: type[Model],
        primary_key: object,
    ) -> None:
        self.rows = [row for row in self.rows if row.get("id") != primary_key]


class SerializerVirtualModel(Model):
    name = CharField(max_length=100)
    age = IntegerField(default=0)

    class Meta:
        table_name = "serializer_virtual_model"
        virtual = True
        backend = "serializer_virtual_backend"


class SerializerVirtualModelSerializer(ModelSerializer):
    class Meta:
        model = SerializerVirtualModel
        fields = ["id", "name", "age"]


@pytest.fixture(autouse=True)
def register_backend() -> None:
    backend_registry.register(
        "serializer_virtual_backend",
        InMemoryVirtualBackend([{"id": 1, "name": "Ada", "age": 36}]),
    )


def test_virtual_model_serializer_serializes_instance() -> None:
    instance = SerializerVirtualModel(id=1, name="Ada", age=36)
    serializer = SerializerVirtualModelSerializer.from_orm(instance)
    data = serializer.model_dump()
    assert data["id"] == 1
    assert data["name"] == "Ada"
    assert data["age"] == 36


def test_virtual_model_serializer_validates_fields() -> None:
    serializer = SerializerVirtualModelSerializer.model_validate({"name": "Grace", "age": 40})
    data = serializer.model_dump()
    assert data["name"] == "Grace"
    assert data["age"] == 40


def test_virtual_model_serializer_rejects_invalid_data() -> None:
    with pytest.raises(PydanticValidationError):
        SerializerVirtualModelSerializer.model_validate({"name": "Grace", "age": "not_a_number"})


@pytest.mark.asyncio
async def test_virtual_model_serializer_works_with_query_results() -> None:
    rows = await SerializerVirtualModel.objects.filter(ignore_permissions=True).all()
    assert len(rows) == 1
    instance = rows[0]
    serializer = SerializerVirtualModelSerializer.from_orm(instance)
    data = serializer.model_dump()
    assert data["name"] == "Ada"
