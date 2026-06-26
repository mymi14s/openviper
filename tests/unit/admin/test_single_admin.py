from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.admin.api.views import get_admin_router
from openviper.admin.options import ModelAdmin
from openviper.db.backends.base import VirtualBackend
from openviper.db.backends.registry import backend_registry
from openviper.db.fields import CharField
from openviper.db.models import Model
from openviper.db.queryspec import QuerySpec
from openviper.exceptions import PermissionDenied


class AdminSingleMemoryBackend(VirtualBackend):
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

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
        return [
            row
            for row in self.rows
            if all(row.get(key) == value for key, value in query.filters.items())
        ]

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
        self.rows = [row for row in self.rows if row.get("id") != primary_key]


class AdminSingleSettings(Model):
    site_name = CharField(default="OpenViper")

    class Meta:
        table_name = "admin_single_settings"
        single = True
        virtual = True
        backend = "admin_single_memory"


class ValidatedAdminSingleSettings(Model):
    site_name = CharField(default="OpenViper")

    async def validate(self) -> None:
        await super().validate()
        if self.site_name == "bad":
            raise ValueError("Invalid site name")

    class Meta:
        table_name = "validated_admin_single_settings"
        single = True
        virtual = True
        backend = "admin_single_memory"


class RequiredAdminSingleSettings(Model):
    api_key = CharField()

    class Meta:
        table_name = "required_admin_single_settings"
        single = True
        virtual = True
        backend = "admin_single_memory"


class AdminRequestUser:
    is_authenticated = True
    is_staff = True
    is_superuser = False


@pytest.fixture
def single_admin_backend() -> AdminSingleMemoryBackend:
    backend = AdminSingleMemoryBackend()
    backend_registry.register("admin_single_memory", backend)
    return backend


@pytest.fixture
def admin_request() -> MagicMock:
    req = MagicMock()
    req.headers = {}
    req.query_params = {}
    req.user = AdminRequestUser()
    req.json = AsyncMock(return_value={})
    return req


def find_handler(path: str, method: str):
    router = get_admin_router()
    for route in router.routes:
        if route.path == path and method in route.methods:
            return route.handler
    raise AssertionError(f"Handler not found for {method} {path}")


def test_single_admin_metadata_disables_list_create_delete(
    single_admin_backend: AdminSingleMemoryBackend,
) -> None:
    model_admin = ModelAdmin(AdminSingleSettings)

    info = model_admin.get_model_info()

    assert any(a["name"] == "delete_selected" for a in info["actions"])


@pytest.mark.asyncio
async def test_admin_single_bulk_action_rejects(
    single_admin_backend: AdminSingleMemoryBackend,
    admin_request: MagicMock,
) -> None:
    handler = find_handler("/models/{app_label}/{model_name}/bulk-action/", "POST")
    model_admin = ModelAdmin(AdminSingleSettings)

    with patch("openviper.admin.api.views.admin") as admin_mock:
        admin_mock.get_model_admin_by_app_and_name.return_value = model_admin
        admin_mock.get_model_by_app_and_name.return_value = AdminSingleSettings

        admin_request.json = AsyncMock(return_value={"action": "delete_selected", "ids": [1]})

        with pytest.raises(PermissionDenied):
            await handler(admin_request, app_label="admin", model_name="AdminSingleSettings")


@pytest.mark.asyncio
async def test_get_single_instance_returns_null_when_no_instance_exists(
    single_admin_backend: AdminSingleMemoryBackend,
    admin_request: MagicMock,
) -> None:
    handler = find_handler("/models/{app_label}/{model_name}/single/", "GET")
    model_admin = ModelAdmin(AdminSingleSettings)

    with patch("openviper.admin.api.views.admin") as admin_mock:
        admin_mock.get_model_admin_by_app_and_name.return_value = model_admin
        admin_mock.get_model_by_app_and_name.return_value = AdminSingleSettings

        response = await handler(admin_request, app_label="admin", model_name="AdminSingleSettings")

    data = json.loads(response.body.decode())
    assert data["instance"] is None
    assert "model_info" in data
    assert "readonly_fields" in data
    assert "fieldsets" in data


@pytest.mark.asyncio
async def test_get_single_instance_returns_instance_when_exists(
    single_admin_backend: AdminSingleMemoryBackend,
    admin_request: MagicMock,
) -> None:
    single_admin_backend.rows.append({"id": 1, "site_name": "TestSite"})

    handler = find_handler("/models/{app_label}/{model_name}/single/", "GET")
    model_admin = ModelAdmin(AdminSingleSettings)

    with patch("openviper.admin.api.views.admin") as admin_mock:
        admin_mock.get_model_admin_by_app_and_name.return_value = model_admin
        admin_mock.get_model_by_app_and_name.return_value = AdminSingleSettings

        response = await handler(admin_request, app_label="admin", model_name="AdminSingleSettings")

    data = json.loads(response.body.decode())
    assert data["instance"] is not None
    assert data["instance"]["site_name"] == "TestSite"
