"""Additional branch tests for openviper.db.fields."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.db.fields import LazyFK


@pytest.mark.asyncio
async def test_lazy_fk_load_returns_none_when_target_unresolved():
    fk_field = MagicMock()
    fk_field.resolve_target.return_value = None
    fk_field.name = "owner"
    instance = MagicMock()

    lazy = LazyFK(fk_field, instance, 1)
    result = await lazy._load()

    assert result is None
    assert lazy._loaded_obj is None


@pytest.mark.asyncio
async def test_lazy_fk_await_loads_and_caches_instance():
    fk_field = MagicMock()
    fk_field.name = "owner"
    related_model = MagicMock()
    hydrated = MagicMock()
    related_model._from_row.return_value = hydrated
    fk_field.resolve_target.return_value = related_model

    qs = MagicMock()
    related_model.objects.filter.return_value = qs

    instance = MagicMock()
    instance._relation_cache = {}

    lazy = LazyFK(fk_field, instance, 22)

    with patch("openviper.db.executor.execute_select", new_callable=AsyncMock) as mock_select:
        mock_select.return_value = [{"id": 22}]
        loaded = await lazy

    assert loaded is hydrated
    assert lazy._loaded_obj is hydrated
    assert instance._relation_cache["owner"] is hydrated


# ── LazyFK._load cache hit (line 664) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_lazy_fk_load_returns_cached_obj():
    """_load() returns _loaded_obj immediately when already loaded (line 664)."""
    fk_field = MagicMock()
    instance = MagicMock()

    lazy = LazyFK(fk_field, instance, 42)
    expected = MagicMock()
    lazy._loaded_obj = expected  # pre-populate cache

    result = await lazy._load()

    assert result is expected
    # DB / resolve_target must never be called
    fk_field.resolve_target.assert_not_called()
