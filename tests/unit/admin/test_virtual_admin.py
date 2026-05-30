"""Tests for virtual model admin integration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

import pytest

from openviper.admin.options import ModelAdmin
from openviper.db.backends.base import VirtualBackend, VirtualBackendCapabilities
from openviper.db.backends.registry import backend_registry
from openviper.db.fields import CharField, IntegerField
from openviper.db.models import Model

if TYPE_CHECKING:
    from openviper.db.queryspec import QuerySpec


class InMemoryVirtualBackend(VirtualBackend):
    """Fake backend for admin tests."""

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


class AdminVirtualModel(Model):
    name = CharField(max_length=100)
    age = IntegerField(default=0)

    class Meta:
        table_name = "admin_virtual_model"
        virtual = True
        backend = "admin_virtual_backend"


class AdminReadOnlyVirtualModel(Model):
    name = CharField(max_length=100)

    class Meta:
        table_name = "admin_read_only_virtual_model"
        virtual = True
        backend = "admin_read_only_virtual_backend"
        read_only = True


class AdminNoCreateVirtualModel(Model):
    name = CharField(max_length=100)

    class Meta:
        table_name = "admin_no_create_virtual_model"
        virtual = True
        backend = "admin_no_create_virtual_backend"


@pytest.fixture(autouse=True)
def register_backends() -> None:
    backend_registry.register("admin_virtual_backend", InMemoryVirtualBackend())
    backend_registry.register("admin_read_only_virtual_backend", InMemoryVirtualBackend())
    backend_registry.register(
        "admin_no_create_virtual_backend",
        InMemoryVirtualBackend(capabilities=VirtualBackendCapabilities(supports_create=False)),
    )


def test_virtual_model_can_register_in_admin() -> None:
    admin = ModelAdmin(AdminVirtualModel)
    assert admin._model_name == "AdminVirtualModel"
    assert admin._table_name == "admin_virtual_model"


def test_read_only_virtual_admin_disables_write_permissions() -> None:
    admin = ModelAdmin(AdminReadOnlyVirtualModel)
    assert admin.has_add_permission(None) is False
    assert admin.has_change_permission(None) is False
    assert admin.has_delete_permission(None) is False


def test_virtual_admin_respects_backend_capabilities() -> None:
    admin = ModelAdmin(AdminNoCreateVirtualModel)
    assert admin.has_add_permission(None) is False
    assert admin.has_change_permission(None) is True
    assert admin.has_delete_permission(None) is True


def test_normal_admin_permissions_unchanged() -> None:
    class NormalModel(Model):
        name = CharField(max_length=100)

        class Meta:
            table_name = "normal_admin_model"

    admin = ModelAdmin(NormalModel)
    assert admin.has_add_permission(None) is True
    assert admin.has_change_permission(None) is True
    assert admin.has_delete_permission(None) is True


@pytest.mark.asyncio
async def test_virtual_admin_list_uses_backend_list() -> None:
    backend = InMemoryVirtualBackend([{"id": 1, "name": "Ada", "age": 36}])
    backend_registry.register("admin_virtual_backend", backend)

    rows = await AdminVirtualModel.objects.filter(ignore_permissions=True).all()
    assert len(rows) == 1
    assert rows[0].name == "Ada"


@pytest.mark.asyncio
async def test_virtual_admin_detail_uses_backend_get() -> None:
    backend = InMemoryVirtualBackend([{"id": 1, "name": "Ada", "age": 36}])
    backend_registry.register("admin_virtual_backend", backend)

    row = await AdminVirtualModel.objects.get_or_none(ignore_permissions=True, id=1)
    assert row is not None
    assert row.name == "Ada"


def test_virtual_model_info_includes_is_virtual_flag() -> None:
    admin = ModelAdmin(AdminVirtualModel)
    info = admin.get_model_info()
    assert info["is_virtual"] is True


def test_normal_model_info_is_virtual_is_false() -> None:
    class NormalModel(Model):
        name = CharField(max_length=100)

        class Meta:
            table_name = "normal_model_info_test"

    admin = ModelAdmin(NormalModel)
    info = admin.get_model_info()
    assert info["is_virtual"] is False


@pytest.mark.asyncio
async def test_virtual_admin_count_uses_backend_count_when_supported() -> None:
    backend = InMemoryVirtualBackend(
        [
            {"id": 1, "name": "Ada", "age": 36},
            {"id": 2, "name": "Grace", "age": 40},
        ],
        capabilities=VirtualBackendCapabilities(supports_count=True),
    )
    backend_registry.register("admin_virtual_backend", backend)

    count = await AdminVirtualModel.objects.filter(ignore_permissions=True).count()
    assert count == 2


@pytest.mark.asyncio
async def test_virtual_admin_pagination_with_offset_and_limit() -> None:
    backend = InMemoryVirtualBackend(
        [
            {"id": 1, "name": "Ada", "age": 36},
            {"id": 2, "name": "Grace", "age": 40},
            {"id": 3, "name": "Lin", "age": 42},
        ]
    )
    backend_registry.register("admin_virtual_backend", backend)

    rows = await (
        AdminVirtualModel.objects.filter(ignore_permissions=True)
        .order_by("id")
        .offset(1)
        .limit(1)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].name == "Grace"
