"""Tests for the database routing system.

Covers PrimaryReplicaRouter, AdminRouter, RouterResolver,
DefaultRouterResolver, and routing context variables.
"""

from __future__ import annotations

import pytest

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

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clean_routing_context() -> None:
    """Reset routing context between tests."""
    reset_routing_context()
    yield
    reset_routing_context()


# ── DatabaseRouter base class ─────────────────────────────────────────────────


class TestDatabaseRouter:
    """Base DatabaseRouter returns None for all methods."""

    async def test_db_for_read_returns_none(self) -> None:
        router = DatabaseRouter()
        result = await router.db_for_read(object)
        assert result is None

    async def test_db_for_write_returns_none(self) -> None:
        router = DatabaseRouter()
        result = await router.db_for_write(object)
        assert result is None

    async def test_allow_relation_returns_none(self) -> None:
        router = DatabaseRouter()
        result = await router.allow_relation(object, object)
        assert result is None

    async def test_allow_migrate_returns_none(self) -> None:
        router = DatabaseRouter()
        result = await router.allow_migrate("default", object)
        assert result is None


# ── PrimaryReplicaRouter ──────────────────────────────────────────────────────


class TestPrimaryReplicaRouter:
    async def test_db_for_read_returns_primary_when_write_used(self) -> None:
        router = PrimaryReplicaRouter(replica_aliases=["replica1"])
        mark_write_used()
        result = await router.db_for_read(object)
        assert result == "default"

    async def test_db_for_read_returns_replica_when_no_write(self) -> None:
        router = PrimaryReplicaRouter(replica_aliases=["replica1"])
        result = await router.db_for_read(object)
        assert result == "replica1"

    async def test_db_for_write_returns_primary(self) -> None:
        router = PrimaryReplicaRouter(replica_aliases=["replica1"])
        result = await router.db_for_write(object)
        assert result == "default"

    async def test_allow_migrate_primary_only(self) -> None:
        router = PrimaryReplicaRouter(replica_aliases=["replica1"])
        assert await router.allow_migrate("default", object) is True
        assert await router.allow_migrate("replica1", object) is False

    async def test_allow_migrate_all_when_disabled(self) -> None:
        router = PrimaryReplicaRouter(replica_aliases=["replica1"], migrate_on_primary_only=False)
        assert await router.allow_migrate("default", object) is None


# ── AdminRouter ───────────────────────────────────────────────────────────────


class TestAdminRouter:
    async def test_db_for_read_returns_default_with_admin_hint(self) -> None:
        router = AdminRouter()
        result = await router.db_for_read(object, admin=True)
        assert result == "default"

    async def test_db_for_read_returns_none_without_hint(self) -> None:
        router = AdminRouter()
        result = await router.db_for_read(object)
        assert result is None

    async def test_db_for_write_returns_default_with_admin_hint(self) -> None:
        router = AdminRouter()
        result = await router.db_for_write(object, admin=True)
        assert result == "default"

    async def test_db_for_write_returns_none_without_hint(self) -> None:
        router = AdminRouter()
        result = await router.db_for_write(object)
        assert result is None

    async def test_allow_migrate_returns_none(self) -> None:
        router = AdminRouter()
        result = await router.allow_migrate("default", object)
        assert result is None


# ── RouterResolver ────────────────────────────────────────────────────────────


class TestRouterResolver:
    async def test_resolve_read_returns_default_with_no_routers(self) -> None:
        resolver = RouterResolver(routers=[])
        result = await resolver.resolve_read(object)
        assert result == "default"

    async def test_resolve_write_returns_default_with_no_routers(self) -> None:
        resolver = RouterResolver(routers=[])
        result = await resolver.resolve_write(object)
        assert result == "default"

    async def test_resolve_read_uses_router(self) -> None:
        router = PrimaryReplicaRouter(replica_aliases=["replica1"])
        resolver = RouterResolver(routers=[router])
        result = await resolver.resolve_read(object)
        assert result == "replica1"

    async def test_resolve_write_uses_router(self) -> None:
        router = PrimaryReplicaRouter(replica_aliases=["replica1"])
        resolver = RouterResolver(routers=[router])
        result = await resolver.resolve_write(object)
        assert result == "default"

    async def test_resolve_migrate_defaults_to_default(self) -> None:
        resolver = RouterResolver(routers=[])
        result = await resolver.resolve_migrate("default", object)
        assert result is True

    async def test_resolve_migrate_rejects_non_default(self) -> None:
        resolver = RouterResolver(routers=[])
        result = await resolver.resolve_migrate("other", object)
        assert result is False

    async def test_resolve_relation_defaults_to_true(self) -> None:
        resolver = RouterResolver(routers=[])
        result = await resolver.resolve_relation(object, object)
        assert result is True


# ── DefaultRouterResolver ─────────────────────────────────────────────────────


class TestDefaultRouterResolver:
    async def test_resolve_read_returns_default_with_no_settings(self) -> None:
        resolver = DefaultRouterResolver()
        result = await resolver.resolve_read(object)
        assert result == "default"

    async def test_resolve_write_returns_default_with_no_settings(self) -> None:
        resolver = DefaultRouterResolver()
        result = await resolver.resolve_write(object)
        assert result == "default"

    async def test_ensure_loaded_is_idempotent(self) -> None:
        resolver = DefaultRouterResolver()
        resolver.ensure_loaded()
        resolver.ensure_loaded()
        assert resolver.loaded is True


# ── Routing context variables ─────────────────────────────────────────────────


class TestRoutingContext:
    def test_default_alias_is_default(self) -> None:
        assert current_db_alias.get() == "default"

    def test_set_and_reset_alias(self) -> None:
        token = set_current_alias("replica1")
        assert current_db_alias.get() == "replica1"
        reset_current_alias(token)
        assert current_db_alias.get() == "default"

    def test_mark_write_used_sets_read_from_primary(self) -> None:
        assert read_from_primary.get() is False
        mark_write_used()
        assert read_from_primary.get() is True
        assert write_used.get() is True

    def test_reset_routing_context(self) -> None:
        set_current_alias("replica1")
        mark_write_used()
        reset_routing_context()
        assert current_db_alias.get() == "default"
        assert read_from_primary.get() is False
        assert write_used.get() is False
