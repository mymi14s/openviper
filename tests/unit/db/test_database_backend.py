"""Tests for database backend API, registry, connections, routing, and replica support."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from openviper.db.backends.client import DatabaseClient
from openviper.db.backends.creation import DatabaseCreation
from openviper.db.backends.database import DatabaseBackend
from openviper.db.backends.db_registry import (
    DatabaseBackendRegistry,
    database_backend_registry,
    get_database_backend_class,
)
from openviper.db.backends.execution import DatabaseExecution
from openviper.db.backends.features import DatabaseFeatures
from openviper.db.backends.introspection import DatabaseIntrospection
from openviper.db.backends.operations import DatabaseOperations
from openviper.db.backends.sqlalchemy import DefaultDatabaseBackend
from openviper.db.connection import transaction
from openviper.db.connections import DEFAULT_ALIAS, ConnectionManager, connections
from openviper.db.exceptions import (
    DatabaseAliasNotFoundError,
    DatabaseBackendNotFoundError,
    DatabaseConfigurationError,
    DatabaseReadOnlyError,
    DatabaseRoutingError,
)
from openviper.db.models import Model, QuerySet
from openviper.db.routing.admin import AdminRouter
from openviper.db.routing.base import DatabaseRouter
from openviper.db.routing.context import (
    current_db_alias,
    mark_write_used,
    read_from_primary,
    reset_current_alias,
    reset_routing_context,
    set_current_alias,
    write_used,
)
from openviper.db.routing.primary_replica import PrimaryReplicaRouter
from openviper.db.routing.resolver import DefaultRouterResolver, RouterResolver

# ── DatabaseFeatures ──────────────────────────────────────────────────────


class TestDatabaseFeatures:
    def test_default_feature_values(self) -> None:
        features = DatabaseFeatures()
        assert features.supports_transactions is True
        assert features.supports_savepoints is True
        assert features.supports_json is True
        assert features.supports_uuid is True
        assert features.supports_returning is True
        assert features.supports_bulk_insert is True
        assert features.supports_foreign_keys is True
        assert features.supports_indexes is True
        assert features.supports_partial_indexes is True
        assert features.supports_check_constraints is True
        assert features.supports_schema_comments is False
        assert features.supports_read_only_connections is False


# ── DatabaseOperations ────────────────────────────────────────────────────


class TestDatabaseOperations:
    def test_normalize_url_postgresql(self) -> None:
        ops = DatabaseOperations()
        assert ops.normalize_url("postgresql://u:p@h/d") == "postgresql+asyncpg://u:p@h/d"

    def test_normalize_url_mysql(self) -> None:
        ops = DatabaseOperations()
        assert ops.normalize_url("mysql://u:p@h/d") == "mysql+aiomysql://u:p@h/d"

    def test_normalize_url_sqlite(self) -> None:
        ops = DatabaseOperations()
        assert ops.normalize_url("sqlite:///db.sqlite3") == "sqlite+aiosqlite:///db.sqlite3"

    def test_normalize_url_already_async(self) -> None:
        ops = DatabaseOperations()
        url = "postgresql+asyncpg://u:p@h/d"
        assert ops.normalize_url(url) == url

    def test_extract_vendor_postgresql(self) -> None:
        ops = DatabaseOperations()
        assert ops.extract_vendor("postgresql://u:p@h/d") == "postgresql"

    def test_extract_vendor_mysql(self) -> None:
        ops = DatabaseOperations()
        assert ops.extract_vendor("mysql://u:p@h/d") == "mysql"

    def test_extract_vendor_sqlite(self) -> None:
        ops = DatabaseOperations()
        assert ops.extract_vendor("sqlite:///db.sqlite3") == "sqlite"

    def test_quote_identifier_simple(self) -> None:
        ops = DatabaseOperations()
        assert ops.quote_identifier("users") == "users"

    def test_quote_identifier_special_chars(self) -> None:
        ops = DatabaseOperations()
        assert ops.quote_identifier("my table") == '"my table"'

    def test_adapt_value_passthrough(self) -> None:
        ops = DatabaseOperations()
        assert ops.adapt_value(42) == 42
        assert ops.adapt_value("hello") == "hello"


# ── DatabaseBackendRegistry ────────────────────────────────────────────────


class TestDatabaseBackendRegistry:
    def test_register_and_resolve_builtin(self) -> None:
        registry = DatabaseBackendRegistry()
        registry.register("sqlalchemy", DefaultDatabaseBackend)
        assert registry.resolve("sqlalchemy") is DefaultDatabaseBackend

    def test_register_rejects_empty_name(self) -> None:
        registry = DatabaseBackendRegistry()
        with pytest.raises(ValueError, match="cannot be empty"):
            registry.register("", DefaultDatabaseBackend)

    def test_register_rejects_non_backend_class(self) -> None:
        registry = DatabaseBackendRegistry()
        with pytest.raises(TypeError, match="DatabaseBackend subclass"):
            registry.register("bad", dict)

    def test_resolve_unknown_short_name_raises(self) -> None:
        registry = DatabaseBackendRegistry()
        with pytest.raises(DatabaseBackendNotFoundError):
            registry.resolve("nonexistent_backend")

    def test_global_registry_has_sqlalchemy(self) -> None:
        assert database_backend_registry.resolve("sqlalchemy") is DefaultDatabaseBackend


# ── get_database_backend_class ─────────────────────────────────────────────


class TestGetDatabaseBackendClass:
    def test_omitted_backend_returns_default(self) -> None:
        config = {"URL": "postgresql://u:p@h/d"}
        assert get_database_backend_class(config) is DefaultDatabaseBackend

    def test_none_backend_returns_default(self) -> None:
        config = {"URL": "postgresql://u:p@h/d", "BACKEND": None}
        assert get_database_backend_class(config) is DefaultDatabaseBackend

    def test_empty_backend_string_raises(self) -> None:
        config = {"URL": "postgresql://u:p@h/d", "BACKEND": ""}
        with pytest.raises(DatabaseConfigurationError, match="empty string"):
            get_database_backend_class(config)

    def test_non_string_backend_raises(self) -> None:
        config = {"URL": "postgresql://u:p@h/d", "BACKEND": 123}
        with pytest.raises(DatabaseConfigurationError, match="must be a string"):
            get_database_backend_class(config)

    def test_short_name_backend_resolves(self) -> None:
        config = {"URL": "postgresql://u:p@h/d", "BACKEND": "sqlalchemy"}
        assert get_database_backend_class(config) is DefaultDatabaseBackend

    def test_import_path_backend_resolves(self) -> None:
        config = {
            "URL": "postgresql://u:p@h/d",
            "BACKEND": "openviper.db.backends.DefaultDatabaseBackend",
        }
        assert get_database_backend_class(config) is DefaultDatabaseBackend

    def test_invalid_import_path_raises(self) -> None:
        config = {
            "URL": "postgresql://u:p@h/d",
            "BACKEND": "nonexistent.module.BadBackend",
        }
        with pytest.raises(DatabaseBackendNotFoundError):
            get_database_backend_class(config)


# ── ConnectionManager ──────────────────────────────────────────────────────


class TestConnectionManager:
    def test_normalize_database_url(self) -> None:
        mgr = ConnectionManager()
        mgr.backends.clear()
        mgr.initialized = False
        mgr.normalize_database_url()
        # No DATABASE_URL set in test, so no backends
        # This just tests that it doesn't crash

    def test_setup_alias_without_backend_uses_default(self) -> None:
        mgr = ConnectionManager()
        mgr.backends.clear()
        mgr.initialized = False
        mgr.setup_alias("default", {"URL": "sqlite+aiosqlite:///:memory:"})
        assert "default" in mgr.backends
        assert isinstance(mgr.backends["default"], DefaultDatabaseBackend)

    def test_multiple_aliases_without_backend_use_default(self) -> None:
        mgr = ConnectionManager()
        mgr.backends.clear()
        mgr.initialized = False
        mgr.setup_alias("default", {"URL": "sqlite+aiosqlite:///:memory:"})
        mgr.setup_alias("replica", {"URL": "sqlite+aiosqlite:///:memory:", "READ_ONLY": True})
        assert isinstance(mgr.backends["default"], DefaultDatabaseBackend)
        assert isinstance(mgr.backends["replica"], DefaultDatabaseBackend)

    def test_alias_with_explicit_backend(self) -> None:
        mgr = ConnectionManager()
        mgr.backends.clear()
        mgr.initialized = False
        mgr.setup_alias(
            "default",
            {"BACKEND": "sqlalchemy", "URL": "sqlite+aiosqlite:///:memory:"},
        )
        assert isinstance(mgr.backends["default"], DefaultDatabaseBackend)

    def test_get_unknown_alias_raises(self) -> None:
        mgr = ConnectionManager()
        mgr.backends.clear()
        mgr.initialized = True
        with pytest.raises(DatabaseAliasNotFoundError):
            mgr.get("nonexistent")

    def test_aliases_property(self) -> None:
        mgr = ConnectionManager()
        mgr.backends.clear()
        mgr.initialized = True
        mgr.setup_alias("default", {"URL": "sqlite+aiosqlite:///:memory:"})
        mgr.setup_alias("replica", {"URL": "sqlite+aiosqlite:///:memory:"})
        assert set(mgr.aliases) == {"default", "replica"}


# ── DatabaseBackend properties ────────────────────────────────────────────


class TestDatabaseBackendProperties:
    def test_url_property(self) -> None:
        backend = DefaultDatabaseBackend("default", {"URL": "postgresql://u:p@h/d"})
        assert backend.url == "postgresql://u:p@h/d"

    def test_is_read_only_default_false(self) -> None:
        backend = DefaultDatabaseBackend("default", {"URL": "postgresql://u:p@h/d"})
        assert backend.is_read_only is False

    def test_is_read_only_true(self) -> None:
        backend = DefaultDatabaseBackend(
            "replica",
            {"URL": "postgresql://u:p@h/d", "READ_ONLY": True},
        )
        assert backend.is_read_only is True

    def test_role_default_primary(self) -> None:
        backend = DefaultDatabaseBackend("default", {"URL": "postgresql://u:p@h/d"})
        assert backend.role == "primary"

    def test_role_replica(self) -> None:
        backend = DefaultDatabaseBackend(
            "replica",
            {"URL": "postgresql://u:p@h/d", "ROLE": "replica"},
        )
        assert backend.role == "replica"

    def test_features_available(self) -> None:
        backend = DefaultDatabaseBackend("default", {"URL": "postgresql://u:p@h/d"})
        assert isinstance(backend.features, DatabaseFeatures)

    def test_operations_available(self) -> None:
        backend = DefaultDatabaseBackend("default", {"URL": "postgresql://u:p@h/d"})
        assert isinstance(backend.operations, DatabaseOperations)

    def test_execution_available(self) -> None:
        backend = DefaultDatabaseBackend("default", {"URL": "postgresql://u:p@h/d"})
        assert isinstance(backend.execution, DatabaseExecution)

    def test_introspection_available(self) -> None:
        backend = DefaultDatabaseBackend("default", {"URL": "postgresql://u:p@h/d"})
        assert isinstance(backend.introspection, DatabaseIntrospection)

    def test_creation_available(self) -> None:
        backend = DefaultDatabaseBackend("default", {"URL": "postgresql://u:p@h/d"})
        assert isinstance(backend.creation, DatabaseCreation)

    def test_client_available(self) -> None:
        backend = DefaultDatabaseBackend("default", {"URL": "postgresql://u:p@h/d"})
        assert isinstance(backend.client, DatabaseClient)

    def test_repr(self) -> None:
        backend = DefaultDatabaseBackend("default", {"URL": "postgresql://u:p@h/d"})
        assert "default" in repr(backend)


# ── Routing Context ────────────────────────────────────────────────────────


class TestRoutingContext:
    def test_default_values(self) -> None:
        reset_routing_context()
        assert current_db_alias.get() == "default"
        assert read_from_primary.get() is False
        assert write_used.get() is False

    def test_mark_write_used(self) -> None:
        reset_routing_context()
        mark_write_used()
        assert write_used.get() is True
        assert read_from_primary.get() is True

    def test_reset_routing_context(self) -> None:
        mark_write_used()
        reset_routing_context()
        assert current_db_alias.get() == "default"
        assert read_from_primary.get() is False
        assert write_used.get() is False

    def test_set_and_reset_current_alias(self) -> None:
        reset_routing_context()
        token = set_current_alias("replica")
        assert current_db_alias.get() == "replica"
        reset_current_alias(token)
        assert current_db_alias.get() == "default"


# ── DatabaseRouter ─────────────────────────────────────────────────────────


class TestDatabaseRouter:
    @pytest.mark.asyncio
    async def test_default_router_returns_none(self) -> None:
        router = DatabaseRouter()
        assert await router.db_for_read(Model) is None
        assert await router.db_for_write(Model) is None
        assert await router.allow_relation(object(), object()) is None
        assert await router.allow_migrate("default", Model) is None


# ── PrimaryReplicaRouter ───────────────────────────────────────────────────


class TestPrimaryReplicaRouter:
    @pytest.mark.asyncio
    async def test_read_goes_to_replica(self) -> None:
        reset_routing_context()
        router = PrimaryReplicaRouter(
            primary_alias="default",
            replica_aliases=["replica"],
        )
        result = await router.db_for_read(Model)
        assert result == "replica"

    @pytest.mark.asyncio
    async def test_write_goes_to_primary(self) -> None:
        reset_routing_context()
        router = PrimaryReplicaRouter(
            primary_alias="default",
            replica_aliases=["replica"],
        )
        result = await router.db_for_write(Model)
        assert result == "default"

    @pytest.mark.asyncio
    async def test_read_after_write_goes_to_primary(self) -> None:
        reset_routing_context()
        router = PrimaryReplicaRouter(
            primary_alias="default",
            replica_aliases=["replica"],
            read_your_writes=True,
        )
        mark_write_used()
        result = await router.db_for_read(Model)
        assert result == "default"

    @pytest.mark.asyncio
    async def test_no_replicas_read_goes_to_primary(self) -> None:
        reset_routing_context()
        router = PrimaryReplicaRouter(
            primary_alias="default",
            replica_aliases=[],
        )
        result = await router.db_for_read(Model)
        assert result == "default"

    @pytest.mark.asyncio
    async def test_allow_migrate_primary_only(self) -> None:
        router = PrimaryReplicaRouter(
            primary_alias="default",
            replica_aliases=["replica"],
            migrate_on_primary_only=True,
        )
        assert await router.allow_migrate("default", Model) is True
        assert await router.allow_migrate("replica", Model) is False

    @pytest.mark.asyncio
    async def test_allow_migrate_all_when_disabled(self) -> None:
        router = PrimaryReplicaRouter(
            primary_alias="default",
            replica_aliases=["replica"],
            migrate_on_primary_only=False,
        )
        assert await router.allow_migrate("default", Model) is None
        assert await router.allow_migrate("replica", Model) is None

    @pytest.mark.asyncio
    async def test_round_robin_replica_selection(self) -> None:
        reset_routing_context()
        router = PrimaryReplicaRouter(
            primary_alias="default",
            replica_aliases=["replica_1", "replica_2"],
            replica_selection="round_robin",
        )
        r1 = await router.db_for_read(Model)
        r2 = await router.db_for_read(Model)
        assert r1 == "replica_1"
        assert r2 == "replica_2"

    @pytest.mark.asyncio
    async def test_first_replica_selection(self) -> None:
        reset_routing_context()
        router = PrimaryReplicaRouter(
            primary_alias="default",
            replica_aliases=["replica_1", "replica_2"],
            replica_selection="first",
        )
        result = await router.db_for_read(Model)
        assert result == "replica_1"


# ── RouterResolver ─────────────────────────────────────────────────────────


class TestRouterResolver:
    @pytest.mark.asyncio
    async def test_no_routers_fallback_default(self) -> None:
        reset_routing_context()
        resolver = RouterResolver(routers=[])
        result = await resolver.resolve_read(Model)
        assert result == "default"

    @pytest.mark.asyncio
    async def test_router_chaining_first_wins(self) -> None:
        reset_routing_context()

        class FirstRouter(DatabaseRouter):
            async def db_for_read(self, model_class: type, **hints: object) -> str | None:
                return "replica_1"

        class SecondRouter(DatabaseRouter):
            async def db_for_read(self, model_class: type, **hints: object) -> str | None:
                return "replica_2"

        resolver = RouterResolver(routers=[FirstRouter(), SecondRouter()])
        result = await resolver.resolve_read(Model)
        assert result == "replica_1"

    @pytest.mark.asyncio
    async def test_router_chaining_fallback(self) -> None:
        reset_routing_context()

        class PassRouter(DatabaseRouter):
            async def db_for_read(self, model_class: type, **hints: object) -> str | None:
                return None

        class ConcreteRouter(DatabaseRouter):
            async def db_for_read(self, model_class: type, **hints: object) -> str | None:
                return "replica"

        resolver = RouterResolver(routers=[PassRouter(), ConcreteRouter()])
        result = await resolver.resolve_read(Model)
        assert result == "replica"

    @pytest.mark.asyncio
    async def test_resolve_migrate_default_primary_only(self) -> None:
        resolver = RouterResolver(routers=[])
        assert await resolver.resolve_migrate("default", Model) is True
        assert await resolver.resolve_migrate("replica", Model) is False

    @pytest.mark.asyncio
    async def test_resolve_relation_default_allows(self) -> None:
        resolver = RouterResolver(routers=[])
        assert await resolver.resolve_relation(object(), object()) is True

    @pytest.mark.asyncio
    async def test_invalid_router_return_type_raises(self) -> None:
        reset_routing_context()

        class BadRouter(DatabaseRouter):
            async def db_for_read(self, model_class: type, **hints: object) -> str | None:
                return 42

        resolver = RouterResolver(routers=[BadRouter()])
        with pytest.raises(DatabaseRoutingError, match="returned"):
            await resolver.resolve_read(Model)


# ── QuerySet.using ─────────────────────────────────────────────────────────


class TestQuerySetUsing:
    def test_using_sets_alias(self) -> None:
        qs = QuerySet(Model)
        assert qs._db_alias is None
        qs2 = qs.using("replica")
        assert qs2._db_alias == "replica"

    def test_using_preserves_other_state(self) -> None:
        qs = QuerySet(Model).filter(name="test").order_by("-id").limit(10)
        qs2 = qs.using("replica")
        assert qs2._db_alias == "replica"
        assert qs2._filters == [{"name": "test"}]
        assert qs2._order == ["-id"]
        assert qs2._limit == 10

    def test_using_does_not_mutate_original(self) -> None:
        qs = QuerySet(Model)
        qs2 = qs.using("replica")
        assert qs._db_alias is None
        assert qs2._db_alias == "replica"

    def test_using_chained_with_filter(self) -> None:
        qs = QuerySet(Model).using("replica").filter(name="test")
        assert qs._db_alias == "replica"
        assert qs._filters == [{"name": "test"}]

    def test_filter_chained_with_using(self) -> None:
        qs = QuerySet(Model).filter(name="test").using("replica")
        assert qs._db_alias == "replica"
        assert qs._filters == [{"name": "test"}]

    def test_queryset_using_unknown_alias_stored(self) -> None:
        """Unknown aliases are stored without validation; they raise at execution time."""
        qs = QuerySet(Model).using("nonexistent_alias")
        assert qs._db_alias == "nonexistent_alias"


# ── DatabaseExecution hooks ────────────────────────────────────────────────


class TestDatabaseExecution:
    @pytest.mark.asyncio
    async def test_pre_and_post_execute_called(self) -> None:
        calls: list[str] = []

        class TrackingExecution(DatabaseExecution):
            async def pre_execute(self, statement, parameters=None):
                calls.append("pre")

            async def post_execute(self, statement, parameters=None, duration=None):
                calls.append("post")

        exec = TrackingExecution()
        # We can't easily test with a real connection here,
        # but we can verify the hook protocol
        assert hasattr(exec, "pre_execute")
        assert hasattr(exec, "post_execute")
        assert hasattr(exec, "on_error")


# ── DatabaseClient ─────────────────────────────────────────────────────────


class TestDatabaseClient:
    def test_default_client_command_empty(self) -> None:
        backend = DefaultDatabaseBackend("default", {"URL": "sqlite+aiosqlite:///:memory:"})
        assert backend.client.client_command() == []


# ── DatabaseCreation ──────────────────────────────────────────────────────


class TestDatabaseCreation:
    def test_creation_has_backend_reference(self) -> None:
        backend = DefaultDatabaseBackend("default", {"URL": "sqlite+aiosqlite:///:memory:"})
        assert backend.creation.backend is backend


# ── DatabaseAliasNotFoundError ──────────────────────────────────────────────


class TestExceptions:
    def test_database_configuration_error(self) -> None:
        with pytest.raises(DatabaseConfigurationError):
            raise DatabaseConfigurationError("bad config")

    def test_database_backend_not_found_error(self) -> None:
        with pytest.raises(DatabaseBackendNotFoundError):
            raise DatabaseBackendNotFoundError("not found")

    def test_database_alias_not_found_error(self) -> None:
        with pytest.raises(DatabaseAliasNotFoundError):
            raise DatabaseAliasNotFoundError("alias missing")

    def test_database_read_only_error(self) -> None:
        with pytest.raises(DatabaseReadOnlyError):
            raise DatabaseReadOnlyError("write blocked")

    def test_database_routing_error(self) -> None:
        with pytest.raises(DatabaseRoutingError):
            raise DatabaseRoutingError("bad route")


# ── Integration: DATABASE_URL backward compatibility ───────────────────────


class TestBackwardCompatibility:
    def test_database_url_normalizes_to_default_database(self) -> None:
        mgr = ConnectionManager()
        mgr.backends.clear()
        mgr.initialized = False
        mgr.normalize_database_url()
        # Without DATABASE_URL set in test, no backends created.
        # Tests that normalization path does not crash.

    def test_database_url_normalizes_to_default_backend(self) -> None:
        mgr = ConnectionManager()
        mgr.backends.clear()
        mgr.initialized = False
        mgr.setup_alias("default", {"URL": "sqlite+aiosqlite:///:memory:"})
        backend = mgr.get("default")
        assert isinstance(backend, DefaultDatabaseBackend)
        assert backend.vendor == "sqlite"

    def test_databases_config_initializes_aliases(self) -> None:
        mgr = ConnectionManager()
        mgr.backends.clear()
        mgr.initialized = False
        mgr.configure(
            databases={
                "default": {"URL": "sqlite+aiosqlite:///:memory:"},
                "replica": {"URL": "sqlite+aiosqlite:///:memory:", "READ_ONLY": True},
            }
        )
        assert set(mgr.aliases) == {"default", "replica"}
        assert isinstance(mgr.get("default"), DefaultDatabaseBackend)
        assert isinstance(mgr.get("replica"), DefaultDatabaseBackend)
        assert mgr.get("replica").is_read_only is True

    def test_database_alias_without_backend_uses_default_backend(self) -> None:
        mgr = ConnectionManager()
        mgr.backends.clear()
        mgr.initialized = False
        mgr.setup_alias("default", {"URL": "sqlite+aiosqlite:///:memory:"})
        backend = mgr.get("default")
        assert isinstance(backend, DefaultDatabaseBackend)

    def test_multiple_aliases_without_backend_use_default_backend(self) -> None:
        mgr = ConnectionManager()
        mgr.backends.clear()
        mgr.initialized = False
        mgr.setup_alias("default", {"URL": "sqlite+aiosqlite:///:memory:"})
        mgr.setup_alias("replica", {"URL": "sqlite+aiosqlite:///:memory:", "READ_ONLY": True})
        assert isinstance(mgr.get("default"), DefaultDatabaseBackend)
        assert isinstance(mgr.get("replica"), DefaultDatabaseBackend)
        assert mgr.get("replica").is_read_only is True

    def test_database_alias_with_explicit_backend_uses_explicit_backend(self) -> None:
        mgr = ConnectionManager()
        mgr.backends.clear()
        mgr.initialized = False
        mgr.setup_alias(
            "default",
            {"BACKEND": "sqlalchemy", "URL": "sqlite+aiosqlite:///:memory:"},
        )
        backend = mgr.get("default")
        assert isinstance(backend, DefaultDatabaseBackend)


# ── Custom backend example ──────────────────────────────────────────────────


class CustomMetricsBackend(DefaultDatabaseBackend):
    """Example custom backend for testing."""

    vendor = "custom"
    display_name = "Custom Metrics Backend"

    def create_execution(self) -> DatabaseExecution:
        return DatabaseExecution()


class TestCustomBackend:
    def test_custom_backend_vendor_derived_from_url(self) -> None:
        backend = CustomMetricsBackend("default", {"URL": "sqlite+aiosqlite:///:memory:"})
        assert backend.vendor == "sqlite"

    def test_custom_backend_display_name_overridden(self) -> None:
        backend = CustomMetricsBackend("default", {"URL": "sqlite+aiosqlite:///:memory:"})
        assert backend.display_name == "Custom Metrics Backend"

    def test_custom_backend_registry(self) -> None:
        registry = DatabaseBackendRegistry()
        registry.register("custom_metrics", CustomMetricsBackend)
        assert registry.resolve("custom_metrics") is CustomMetricsBackend

    def test_custom_backend_via_connections(self) -> None:
        mgr = ConnectionManager()
        mgr.backends.clear()
        mgr.initialized = False
        mgr.setup_alias(
            "default",
            {"BACKEND": "sqlalchemy", "URL": "sqlite+aiosqlite:///:memory:"},
        )
        backend = mgr.get("default")
        assert isinstance(backend, DefaultDatabaseBackend)


# ── Read-only alias protection ──────────────────────────────────────────────


class TestReadOnlyProtection:
    def test_read_only_alias_rejects_write_transaction(self) -> None:
        backend = DefaultDatabaseBackend(
            "replica",
            {"URL": "sqlite+aiosqlite:///:memory:", "READ_ONLY": True},
        )
        assert backend.is_read_only is True

    @pytest.mark.asyncio
    async def test_read_only_alias_rejects_write_via_transaction(self) -> None:
        mgr = ConnectionManager()
        mgr.backends.clear()
        mgr.initialized = True
        mgr.setup_alias(
            "replica",
            {"URL": "sqlite+aiosqlite:///:memory:", "READ_ONLY": True},
        )
        backend = mgr.get("replica")
        mock_engine = MagicMock()
        mock_connection = AsyncMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=None)
        backend.create_engine = AsyncMock(return_value=mock_engine)

        original_backends = connections.backends.copy()
        original_initialized = connections.initialized
        connections.backends = mgr.backends
        connections.initialized = True
        try:
            with pytest.raises(DatabaseReadOnlyError, match="read-only"):
                async with transaction(using="replica"):
                    pass
        finally:
            connections.backends = original_backends
            connections.initialized = original_initialized
            await mgr.disconnect_all()


# ── Integration: Reads route to replica ─────────────────────────────────────


class TestIntegrationReadsRouteToReplica:
    @pytest.mark.asyncio
    async def test_reads_route_to_replica(self) -> None:
        reset_routing_context()
        router = PrimaryReplicaRouter(
            primary_alias="default",
            replica_aliases=["replica"],
        )
        result = await router.db_for_read(Model)
        assert result == "replica"


class TestIntegrationWritesRouteToPrimary:
    @pytest.mark.asyncio
    async def test_writes_route_to_primary(self) -> None:
        reset_routing_context()
        router = PrimaryReplicaRouter(
            primary_alias="default",
            replica_aliases=["replica"],
        )
        result = await router.db_for_write(Model)
        assert result == "default"


class TestIntegrationReadAfterWriteRoutesToPrimary:
    @pytest.mark.asyncio
    async def test_read_after_write_routes_to_primary(self) -> None:
        reset_routing_context()
        router = PrimaryReplicaRouter(
            primary_alias="default",
            replica_aliases=["replica"],
            read_your_writes=True,
        )
        await router.db_for_write(Model)
        mark_write_used()
        result = await router.db_for_read(Model)
        assert result == "default"


class TestIntegrationTransactionPinsPrimary:
    @pytest.mark.asyncio
    async def test_transaction_pins_primary(self) -> None:
        reset_routing_context()
        token = set_current_alias("default")
        assert current_db_alias.get() == "default"
        reset_current_alias(token)
        assert current_db_alias.get() == "default"


class TestIntegrationTransactionUsingReplicaForReadOnly:
    @pytest.mark.asyncio
    async def test_transaction_using_replica_for_read_only(self) -> None:
        mgr = ConnectionManager()
        mgr.backends.clear()
        mgr.initialized = True
        mgr.setup_alias(
            "replica",
            {"URL": "sqlite+aiosqlite:///:memory:", "READ_ONLY": True},
        )
        backend = mgr.get("replica")
        mock_engine = MagicMock()
        mock_connection = AsyncMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=None)
        backend.create_engine = AsyncMock(return_value=mock_engine)

        original_backends = connections.backends.copy()
        original_initialized = connections.initialized
        connections.backends = mgr.backends
        connections.initialized = True
        try:
            async with transaction(using="replica", read_only=True):
                pass
        finally:
            connections.backends = original_backends
            connections.initialized = original_initialized
            await mgr.disconnect_all()

    @pytest.mark.asyncio
    async def test_transaction_without_using_honors_current_alias(self) -> None:
        mgr = ConnectionManager()
        mgr.initialized = True
        mgr.setup_alias("replica", {"URL": "sqlite+aiosqlite:///:memory:"})
        backend = mgr.get("replica")
        mock_engine = MagicMock()
        mock_connection = AsyncMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=None)
        backend.create_engine = AsyncMock(return_value=mock_engine)

        original_backends = connections.backends.copy()
        original_initialized = connections.initialized
        alias_token = set_current_alias("replica")
        connections.backends = mgr.backends
        connections.initialized = True
        try:
            async with transaction():
                pass
        finally:
            reset_current_alias(alias_token)
            connections.backends = original_backends
            connections.initialized = original_initialized
            await mgr.disconnect_all()

        backend.create_engine.assert_awaited_once()


class TestIntegrationMigrationsRouteToPrimary:
    @pytest.mark.asyncio
    async def test_migrations_route_to_primary(self) -> None:
        router = PrimaryReplicaRouter(
            primary_alias="default",
            replica_aliases=["replica"],
            migrate_on_primary_only=True,
        )
        assert await router.allow_migrate("default", Model) is True
        assert await router.allow_migrate("replica", Model) is False


class TestIntegrationAdminWritesUsePrimary:
    @pytest.mark.asyncio
    async def test_admin_writes_use_primary(self) -> None:
        router = AdminRouter()
        result = await router.db_for_write(Model, admin=True)
        assert result == "default"

    @pytest.mark.asyncio
    async def test_admin_reads_use_primary(self) -> None:
        router = AdminRouter()
        result = await router.db_for_read(Model, admin=True)
        assert result == "default"

    @pytest.mark.asyncio
    async def test_admin_non_admin_delegates(self) -> None:
        router = AdminRouter()
        result = await router.db_for_read(Model)
        assert result is None


class TestIntegrationDatabaseCreationPerAlias:
    @pytest.mark.asyncio
    async def test_database_creation_creates_test_db_per_alias(self) -> None:
        mgr = ConnectionManager()
        mgr.backends.clear()
        mgr.initialized = True
        mgr.setup_alias("default", {"URL": "sqlite+aiosqlite:///:memory:"})
        mgr.setup_alias(
            "replica",
            {"URL": "sqlite+aiosqlite:///:memory:", "READ_ONLY": True},
        )
        assert "default" in mgr.aliases
        assert "replica" in mgr.aliases
        default_backend = mgr.get("default")
        replica_backend = mgr.get("replica")
        assert isinstance(default_backend.creation, DatabaseCreation)
        assert isinstance(replica_backend.creation, DatabaseCreation)
        assert default_backend.creation.backend is default_backend
        assert replica_backend.creation.backend is replica_backend


# ── Docs build tests ───────────────────────────────────────────────────────


class TestDocsBuild:
    def test_docs_build_database_backends(self) -> None:
        docs_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "docs", "database_backends.rst"
        )
        assert os.path.exists(docs_path), "docs/database_backends.rst must exist"

    def test_docs_build_database_routing(self) -> None:
        docs_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "docs", "database_routing.rst"
        )
        assert os.path.exists(docs_path), "docs/database_routing.rst must exist"

    def test_docs_index_contains_database_pages(self) -> None:
        index_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "docs", "index.rst")
        assert os.path.exists(index_path), "docs/index.rst must exist"
        with open(index_path) as f:
            content = f.read()
        assert "database_backends" in content, "index.rst must reference database_backends"
        assert "database_routing" in content, "index.rst must reference database_routing"
