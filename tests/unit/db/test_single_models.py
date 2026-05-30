from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

import pytest

import openviper.auth.permission_core as permission_core
from openviper.db.backends.base import VirtualBackend
from openviper.db.backends.registry import backend_registry
from openviper.db.exceptions import (
    SingleModelAlreadyExistsError,
    SingleModelDeleteForbiddenError,
    SingleModelDoesNotExist,
)
from openviper.db.fields import BooleanField, CharField
from openviper.db.models import Model, _perm_cache
from openviper.exceptions import FieldError

if TYPE_CHECKING:
    from openviper.db.queryspec import QuerySpec


@pytest.fixture(autouse=True)
def reset_global_state() -> None:
    """Reset permission cache and checker between tests for isolation."""
    _perm_cache.set(None)
    permission_core.permission_checker = None


class SingleModelMemoryBackend(VirtualBackend):
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []
        self.deleted: list[object] = []

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
        if query.limit is not None:
            rows = rows[: query.limit]
        return rows

    async def create(
        self,
        model_class: type[Model],
        data: Mapping[str, object],
    ) -> Mapping[str, object]:
        row = dict(data)
        row["id"] = row.get("id") or 1
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
        row = {"id": primary_key, **data}
        self.rows.append(row)
        return row

    async def delete(
        self,
        model_class: type[Model],
        primary_key: object,
    ) -> None:
        self.deleted.append(primary_key)
        self.rows = [row for row in self.rows if row.get("id") != primary_key]


class NormalSingleTestModel(Model):
    name = CharField(default="site")

    class Meta:
        table_name = "normal_single_test_model"


class SiteSingleSettings(Model):
    site_name = CharField(default="OpenViper")
    maintenance_mode = BooleanField(default=False)

    class Meta:
        table_name = "site_single_settings"
        single = True
        virtual = True
        backend = "single_model_memory"


class HookedSingleSettings(Model):
    name = CharField(default="Hooked")

    class Meta:
        table_name = "hooked_single_settings"
        single = True
        virtual = True
        backend = "single_model_hooks"

    async def on_delete(self) -> None:
        self.delete_hook_called = True


@pytest.fixture
def single_backend() -> SingleModelMemoryBackend:
    backend = SingleModelMemoryBackend()
    backend_registry.register("single_model_memory", backend)
    return backend


@pytest.fixture
def hooked_backend() -> SingleModelMemoryBackend:
    backend = SingleModelMemoryBackend()
    backend_registry.register("single_model_hooks", backend)
    return backend


def test_model_meta_single_defaults_to_false() -> None:
    assert NormalSingleTestModel._meta.single is False


def test_model_meta_accepts_single_true() -> None:
    assert SiteSingleSettings._meta.single is True
    assert SiteSingleSettings._meta.table_name == "site_single_settings"
    assert "site_name" in SiteSingleSettings._fields


def test_model_meta_single_must_be_boolean() -> None:
    with pytest.raises(FieldError):

        class InvalidSingleModel(Model):
            name = CharField()

            class Meta:
                table_name = "invalid_single_model"
                single = "yes"


@pytest.mark.asyncio
async def test_get_single_raises_when_missing(single_backend: SingleModelMemoryBackend) -> None:
    with pytest.raises(SingleModelDoesNotExist):
        await SiteSingleSettings.objects.get_single()


@pytest.mark.asyncio
async def test_get_or_create_single_creates_when_missing(
    single_backend: SingleModelMemoryBackend,
) -> None:
    instance = await SiteSingleSettings.objects.get_or_create_single()

    assert instance.id == 1
    assert instance.site_name == "OpenViper"
    assert len(single_backend.rows) == 1


@pytest.mark.asyncio
async def test_get_or_create_single_returns_existing(
    single_backend: SingleModelMemoryBackend,
) -> None:
    single_backend.rows.append({"id": 1, "site_name": "Docs", "maintenance_mode": False})

    instance = await SiteSingleSettings.objects.get_or_create_single()

    assert instance.id == 1
    assert instance.site_name == "Docs"
    assert len(single_backend.rows) == 1


@pytest.mark.asyncio
async def test_create_single_raises_if_exists(single_backend: SingleModelMemoryBackend) -> None:
    await SiteSingleSettings.objects.create_single(site_name="First")

    with pytest.raises(SingleModelAlreadyExistsError):
        await SiteSingleSettings.objects.create_single(site_name="Second")


@pytest.mark.asyncio
async def test_single_model_normal_create_rejects_second_record(
    single_backend: SingleModelMemoryBackend,
) -> None:
    await SiteSingleSettings.objects.create(site_name="First")

    with pytest.raises(SingleModelAlreadyExistsError):
        await SiteSingleSettings.objects.create(site_name="Second")


@pytest.mark.asyncio
async def test_update_single_updates_record(single_backend: SingleModelMemoryBackend) -> None:
    await SiteSingleSettings.objects.create_single(site_name="Before")

    instance = await SiteSingleSettings.objects.update_single(
        site_name="After",
        maintenance_mode=True,
    )

    assert instance.id == 1
    assert instance.site_name == "After"
    assert instance.maintenance_mode is True
    assert single_backend.rows == [{"id": 1, "site_name": "After", "maintenance_mode": True}]


@pytest.mark.asyncio
async def test_single_model_instance_delete_raises(
    single_backend: SingleModelMemoryBackend,
) -> None:
    instance = await SiteSingleSettings.objects.create_single()

    with pytest.raises(SingleModelDeleteForbiddenError):
        await instance.delete()

    assert len(single_backend.rows) == 1


@pytest.mark.asyncio
async def test_single_model_queryset_delete_raises(
    single_backend: SingleModelMemoryBackend,
) -> None:
    await SiteSingleSettings.objects.create_single()

    with pytest.raises(SingleModelDeleteForbiddenError):
        await SiteSingleSettings.objects.filter(id=1).delete()

    assert len(single_backend.rows) == 1


@pytest.mark.asyncio
async def test_single_model_queryset_reads_logical_single_record(
    single_backend: SingleModelMemoryBackend,
) -> None:
    single_backend.rows.extend(
        [
            {"id": 1, "site_name": "Primary", "maintenance_mode": False},
            {"id": 2, "site_name": "Stray", "maintenance_mode": True},
        ]
    )

    instances = await SiteSingleSettings.objects.all()
    count = await SiteSingleSettings.objects.count()
    stray_exists = await SiteSingleSettings.objects.filter(id=2).exists()

    assert [instance.id for instance in instances] == [1]
    assert count == 1
    assert stray_exists is False


@pytest.mark.asyncio
async def test_single_model_delete_does_not_call_on_delete(
    hooked_backend: SingleModelMemoryBackend,
) -> None:
    instance = await HookedSingleSettings.objects.create_single()

    with pytest.raises(SingleModelDeleteForbiddenError):
        await instance.delete()

    assert getattr(instance, "delete_hook_called", False) is False
    assert hooked_backend.deleted == []
