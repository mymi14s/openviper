from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from openviper.db.backends.api import APIVirtualBackend
from openviper.db.backends.base import VirtualBackend, VirtualBackendCapabilities
from openviper.db.backends.registry import BackendRegistry, backend_registry
from openviper.db.backends.sql import SQLVirtualBackend
from openviper.db.exceptions import (
    ReadOnlyVirtualModelError,
    UnsupportedVirtualQueryError,
    VirtualBackendNotFoundError,
    VirtualBackendOperationError,
)
from openviper.db.fields import CharField, IntegerField
from openviper.db.migrations.executor import CreateTable
from openviper.db.migrations.writer import (
    diff_states,
    has_model_changes,
    model_state_snapshot,
    read_migrated_state,
    write_initial_migration,
)
from openviper.db.models import Model
from openviper.db.queryspec import QuerySpec


class InMemoryVirtualBackend(VirtualBackend):
    def __init__(
        self,
        rows: Sequence[Mapping[str, object]] | None = None,
        capabilities: VirtualBackendCapabilities | None = None,
    ) -> None:
        self.rows = [dict(row) for row in rows or []]
        self.capabilities = capabilities or VirtualBackendCapabilities()
        self.list_queries: list[QuerySpec] = []
        self.get_keys: list[object] = []
        self.created: list[Mapping[str, object]] = []
        self.updated: list[tuple[object, Mapping[str, object]]] = []
        self.deleted: list[object] = []

    async def get(
        self,
        model_class: type[Model],
        primary_key: object,
    ) -> Mapping[str, object] | None:
        self.get_keys.append(primary_key)
        for row in self.rows:
            if row.get("id") == primary_key:
                return row
        return None

    async def list(
        self,
        model_class: type[Model],
        query: QuerySpec,
    ) -> Sequence[Mapping[str, object]]:
        self.list_queries.append(query)
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
        self.created.append(data)
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
        self.updated.append((primary_key, data))
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
        self.deleted.append(primary_key)
        self.rows = [row for row in self.rows if row.get("id") != primary_key]

    async def count(
        self,
        model_class: type[Model],
        query: QuerySpec,
    ) -> int:
        rows = [
            row
            for row in self.rows
            if all(row.get(key) == value for key, value in query.filters.items())
        ]
        return len(rows)


class RecordingAPIVirtualBackend(APIVirtualBackend):
    def __init__(
        self,
        response: Sequence[Mapping[str, object]] | Mapping[str, object] | None,
    ) -> None:
        super().__init__("https://api.example.test", resolve_hostname=False)
        self.response = response
        self.urls: list[str] = []
        self.posts: list[tuple[str, Mapping[str, object]]] = []
        self.patches: list[tuple[str, Mapping[str, object]]] = []
        self.deletes: list[str] = []

    async def http_get(
        self,
        url: str,
    ) -> Sequence[Mapping[str, object]] | Mapping[str, object] | None:
        self.urls.append(url)
        return self.response

    async def http_post(
        self,
        url: str,
        data: Mapping[str, object],
    ) -> Mapping[str, object]:
        self.posts.append((url, data))
        return dict(data)

    async def http_patch(
        self,
        url: str,
        data: Mapping[str, object],
    ) -> Mapping[str, object]:
        self.patches.append((url, data))
        return {"id": 1, **data}

    async def http_delete(self, url: str) -> None:
        self.deletes.append(url)


class VirtualMetaModel(Model):
    name = CharField(max_length=100)

    class Meta:
        table_name = "virtual_meta_model"
        virtual = True
        backend = "meta_backend"
        read_only = True


class NormalMetaModel(Model):
    name = CharField(max_length=100)

    class Meta:
        table_name = "normal_meta_model"


class VirtualQueryModel(Model):
    name = CharField(max_length=100)
    age = IntegerField(default=0)

    class Meta:
        table_name = "virtual_query_model"
        virtual = True
        backend = "virtual_query_backend"


class ReadOnlyVirtualQueryModel(Model):
    name = CharField(max_length=100)

    class Meta:
        table_name = "read_only_virtual_query_model"
        virtual = True
        backend = "read_only_virtual_query_backend"
        read_only = True


def test_model_meta_virtual_defaults_to_false() -> None:
    assert NormalMetaModel._meta.virtual is False
    assert NormalMetaModel._meta.backend == "default"
    assert NormalMetaModel._meta.read_only is False


def test_model_meta_accepts_virtual_backend_read_only_and_table_name() -> None:
    assert VirtualMetaModel._meta.virtual is True
    assert VirtualMetaModel._meta.backend == "meta_backend"
    assert VirtualMetaModel._meta.read_only is True
    assert VirtualMetaModel._meta.table_name == "virtual_meta_model"
    assert VirtualMetaModel._table_name == "virtual_meta_model"


def test_backend_registry_registers_and_resolves_backend() -> None:
    registry = BackendRegistry()
    backend = InMemoryVirtualBackend()
    registry.register("memory", backend)
    assert registry.get("memory") is backend


def test_backend_registry_rejects_empty_name() -> None:
    registry = BackendRegistry()
    with pytest.raises(ValueError, match="Backend name cannot be empty"):
        registry.register("", InMemoryVirtualBackend())


def test_backend_registry_raises_specific_error_for_missing_backend() -> None:
    registry = BackendRegistry()
    with pytest.raises(VirtualBackendNotFoundError):
        registry.get("missing")


def test_backend_capabilities_default_values() -> None:
    capabilities = VirtualBackendCapabilities()
    assert capabilities.supports_create is True
    assert capabilities.supports_count is False


def test_default_backend_is_registered_for_sql_virtual_models() -> None:
    assert isinstance(backend_registry.get("default"), SQLVirtualBackend)


def test_api_backend_rejects_hostname_resolving_to_private_address() -> None:
    with pytest.raises(ValueError, match="private/internal"):
        APIVirtualBackend(
            "https://api.example.test",
            host_resolver=lambda hostname: ("127.0.0.1",),
        )


@pytest.mark.asyncio
async def test_api_backend_maps_queryspec_to_request_url() -> None:
    backend = RecordingAPIVirtualBackend([{"id": 1, "name": "Ada"}])
    query = QuerySpec(
        filters={"name": "Ada Lovelace"},
        limit=10,
        offset=5,
        order_by=("-id",),
    )
    rows = await backend.list(VirtualQueryModel, query)

    assert rows == [{"id": 1, "name": "Ada"}]
    assert backend.urls == [
        "https://api.example.test/virtual_query_model?"
        "limit=10&offset=5&order_by=-id&name=Ada+Lovelace"
    ]


@pytest.mark.asyncio
async def test_api_backend_get_uses_encoded_resource_id() -> None:
    backend = RecordingAPIVirtualBackend({"id": "user/1", "name": "Ada"})
    row = await backend.get(VirtualQueryModel, "user/1")

    assert row == {"id": "user/1", "name": "Ada"}
    assert backend.urls == ["https://api.example.test/virtual_query_model/user%2F1"]


@pytest.mark.asyncio
async def test_api_backend_invalid_payload_raises_operation_error() -> None:
    backend = RecordingAPIVirtualBackend({"id": 1})
    with pytest.raises(VirtualBackendOperationError):
        await backend.list(VirtualQueryModel, QuerySpec())


def test_model_state_snapshot_skips_virtual_models() -> None:
    state = model_state_snapshot([NormalMetaModel, VirtualMetaModel])
    assert "normal_meta_model" in state
    assert "virtual_meta_model" not in state


def test_write_initial_migration_skips_virtual_models(tmp_path: Path) -> None:
    path = write_initial_migration(
        "virtual_test",
        [NormalMetaModel, VirtualMetaModel],
        str(tmp_path),
    )
    content = Path(path).read_text()
    assert "normal_meta_model" in content
    assert "virtual_meta_model" not in content


def test_virtual_model_existing_table_does_not_generate_drop(tmp_path: Path) -> None:
    migration = tmp_path / "0001_initial.py"
    migration.write_text(
        "from openviper.db.migrations import executor as migrations\n"
        "operations = [\n"
        "    migrations.CreateTable(table_name='virtual_meta_model', columns=[]),\n"
        "]\n"
    )
    existing_state = read_migrated_state(str(tmp_path))
    for model_cls in [VirtualMetaModel]:
        existing_state.pop(getattr(model_cls, "_table_name", ""), None)
    ops = diff_states(model_state_snapshot([VirtualMetaModel]), existing_state)
    assert not [op for op in ops if isinstance(op, CreateTable)]
    assert has_model_changes([VirtualMetaModel], str(tmp_path)) is False


@pytest.mark.asyncio
async def test_virtual_all_calls_backend_list_and_hydrates_models() -> None:
    backend = InMemoryVirtualBackend([{"id": 1, "name": "Ada", "age": 36}])
    backend_registry.register("virtual_query_backend", backend)

    rows = await VirtualQueryModel.objects.filter(ignore_permissions=True).all()

    assert [row.name for row in rows] == ["Ada"]
    assert backend.list_queries[0].filters == {}


@pytest.mark.asyncio
async def test_virtual_filter_limit_offset_and_order_by_use_queryspec() -> None:
    backend = InMemoryVirtualBackend(
        [
            {"id": 1, "name": "Ada", "age": 36},
            {"id": 2, "name": "Grace", "age": 40},
        ]
    )
    backend_registry.register("virtual_query_backend", backend)

    rows = await (
        VirtualQueryModel.objects.filter(ignore_permissions=True, name="Grace")
        .order_by("-age")
        .limit(1)
        .offset(0)
        .all()
    )

    assert [row.id for row in rows] == [2]
    assert backend.list_queries[0] == QuerySpec(
        filters={"name": "Grace"},
        limit=1,
        offset=0,
        order_by=("-age",),
    )


@pytest.mark.asyncio
async def test_virtual_values_projects_backend_rows_without_sql() -> None:
    backend = InMemoryVirtualBackend([{"id": 1, "name": "Ada", "age": 36}])
    backend_registry.register("virtual_query_backend", backend)

    rows = await VirtualQueryModel.objects.filter(ignore_permissions=True).values("name")

    assert rows == [{"name": "Ada"}]


@pytest.mark.asyncio
async def test_virtual_sql_only_query_apis_raise_unsupported_error() -> None:
    backend_registry.register("virtual_query_backend", InMemoryVirtualBackend())
    query = VirtualQueryModel.objects.filter(ignore_permissions=True)

    with pytest.raises(UnsupportedVirtualQueryError):
        await query.aggregate(total=object())
    with pytest.raises(UnsupportedVirtualQueryError):
        await query.explain()
    with pytest.raises(UnsupportedVirtualQueryError):
        query.raw_sql()


@pytest.mark.asyncio
async def test_virtual_get_or_none_calls_backend_get() -> None:
    backend = InMemoryVirtualBackend([{"id": 7, "name": "Lin", "age": 42}])
    backend_registry.register("virtual_query_backend", backend)

    row = await VirtualQueryModel.objects.get_or_none(ignore_permissions=True, id=7)

    assert row is not None
    assert row.name == "Lin"
    assert backend.get_keys == [7]


@pytest.mark.asyncio
async def test_virtual_count_uses_backend_list_fallback() -> None:
    backend = InMemoryVirtualBackend(
        [
            {"id": 1, "name": "Ada", "age": 36},
            {"id": 2, "name": "Ada", "age": 37},
        ]
    )
    backend_registry.register("virtual_query_backend", backend)

    count = await VirtualQueryModel.objects.filter(ignore_permissions=True, name="Ada").count()

    assert count == 2


@pytest.mark.asyncio
async def test_virtual_create_update_and_delete_route_to_backend() -> None:
    backend = InMemoryVirtualBackend([{"id": 1, "name": "Ada", "age": 36}])
    backend_registry.register("virtual_query_backend", backend)

    created = VirtualQueryModel(name="Grace", age=40)
    await created.save(ignore_permissions=True)
    updated = await VirtualQueryModel.objects.filter(ignore_permissions=True, id=1).update(
        name="Augusta"
    )
    deleted = await VirtualQueryModel.objects.filter(ignore_permissions=True, id=1).delete()

    assert created.id == 2
    assert backend.created[0]["name"] == "Grace"
    assert updated == 1
    assert backend.updated[0][0] == 1
    assert deleted == 1
    assert backend.deleted == [1]


@pytest.mark.asyncio
async def test_read_only_virtual_model_rejects_writes() -> None:
    backend_registry.register("read_only_virtual_query_backend", InMemoryVirtualBackend())

    with pytest.raises(ReadOnlyVirtualModelError):
        await ReadOnlyVirtualQueryModel(name="Ada").save(ignore_permissions=True)


@pytest.mark.asyncio
async def test_backend_capability_blocks_unsupported_filtering() -> None:
    backend = InMemoryVirtualBackend(capabilities=VirtualBackendCapabilities(supports_filter=False))
    backend_registry.register("virtual_query_backend", backend)

    with pytest.raises(UnsupportedVirtualQueryError):
        await VirtualQueryModel.objects.filter(ignore_permissions=True, name="Ada").all()


@pytest.mark.asyncio
async def test_virtual_count_uses_backend_count_when_supported() -> None:
    backend = InMemoryVirtualBackend(
        [
            {"id": 1, "name": "Ada", "age": 36},
            {"id": 2, "name": "Grace", "age": 40},
            {"id": 3, "name": "Lin", "age": 42},
        ],
        capabilities=VirtualBackendCapabilities(supports_count=True),
    )
    backend_registry.register("virtual_query_backend", backend)

    count = await VirtualQueryModel.objects.filter(ignore_permissions=True, name="Ada").count()

    assert count == 1
    assert len(backend.list_queries) == 0


@pytest.mark.asyncio
async def test_virtual_exists_uses_backend_count_when_supported() -> None:
    backend = InMemoryVirtualBackend(
        [{"id": 1, "name": "Ada", "age": 36}],
        capabilities=VirtualBackendCapabilities(supports_count=True),
    )
    backend_registry.register("virtual_query_backend", backend)

    exists = await VirtualQueryModel.objects.filter(ignore_permissions=True, name="Ada").exists()

    assert exists is True
    assert len(backend.list_queries) == 0


@pytest.mark.asyncio
async def test_virtual_exists_returns_false_when_count_is_zero() -> None:
    backend = InMemoryVirtualBackend(
        [],
        capabilities=VirtualBackendCapabilities(supports_count=True),
    )
    backend_registry.register("virtual_query_backend", backend)

    exists = await VirtualQueryModel.objects.filter(
        ignore_permissions=True, name="NonExistent"
    ).exists()

    assert exists is False


@pytest.mark.asyncio
async def test_virtual_count_falls_back_to_list_when_count_not_supported() -> None:
    backend = InMemoryVirtualBackend(
        [
            {"id": 1, "name": "Ada", "age": 36},
            {"id": 2, "name": "Grace", "age": 40},
        ],
        capabilities=VirtualBackendCapabilities(supports_count=False),
    )
    backend_registry.register("virtual_query_backend", backend)

    count = await VirtualQueryModel.objects.filter(ignore_permissions=True).count()

    assert count == 2
    assert len(backend.list_queries) == 1


class CountingInMemoryBackend(InMemoryVirtualBackend):
    """Backend that overrides count() for efficient counting."""

    async def count(self, model_class: type[Model], query: QuerySpec) -> int:
        rows = [
            row
            for row in self.rows
            if all(row.get(key) == value for key, value in query.filters.items())
        ]
        return len(rows)


@pytest.mark.asyncio
async def test_virtual_count_delegates_to_backend_count_override() -> None:
    backend = CountingInMemoryBackend(
        [
            {"id": 1, "name": "Ada", "age": 36},
            {"id": 2, "name": "Grace", "age": 40},
            {"id": 3, "name": "Ada", "age": 28},
        ],
        capabilities=VirtualBackendCapabilities(supports_count=True),
    )
    backend_registry.register("virtual_query_backend", backend)

    count = await VirtualQueryModel.objects.filter(ignore_permissions=True, name="Ada").count()

    assert count == 2
    assert len(backend.list_queries) == 0
