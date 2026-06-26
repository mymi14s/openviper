"""Unit tests for the @db_patch decorator and registry."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock

import pytest

from openviper.db.patches.decorator import (
    PatchEntry,
    PatchRegistry,
    db_patch,
    get_registry,
    reset_registry,
)


class TestDbPatchDecorator:
    """Test the @db_patch decorator registration."""

    def test_decorator_registers_function_in_global_registry(self) -> None:
        reset_registry()

        @db_patch
        async def my_patch() -> None:
            pass

        registered = get_registry().get_all()
        assert any(p.name == "my_patch" for p in registered)

    def test_decorator_captures_module_path_from_function(self) -> None:
        reset_registry()

        @db_patch
        async def my_patch() -> None:
            pass

        patch_entry = [p for p in get_registry().get_all() if p.name == "my_patch"][0]
        assert patch_entry.module == __name__
        assert patch_entry.app == __name__.split(".")[0]

    def test_decorator_preserves_coroutine_function(self) -> None:
        reset_registry()

        @db_patch
        async def my_patch() -> str:
            return "result"

        assert inspect.iscoroutinefunction(my_patch)

    def test_post_migrate_defaults_to_true(self) -> None:
        reset_registry()

        @db_patch
        async def default_patch() -> None:
            pass

        patch_entry = [p for p in get_registry().get_all() if p.name == "default_patch"][0]
        assert patch_entry.post_migrate is True

    def test_post_migrate_false_sets_pre_migrate_phase(self) -> None:
        reset_registry()

        @db_patch(post_migrate=False)
        async def pre_patch() -> None:
            pass

        patch_entry = [p for p in get_registry().get_all() if p.name == "pre_patch"][0]
        assert patch_entry.post_migrate is False

    def test_explicit_post_migrate_true_stays_post_migrate(self) -> None:
        reset_registry()

        @db_patch(post_migrate=True)
        async def post_patch() -> None:
            pass

        patch_entry = [p for p in get_registry().get_all() if p.name == "post_patch"][0]
        assert patch_entry.post_migrate is True

    def test_order_parameter_stored_on_entry(self) -> None:
        reset_registry()

        @db_patch(order=5)
        async def ordered_patch() -> None:
            pass

        patch_entry = [p for p in get_registry().get_all() if p.name == "ordered_patch"][0]
        assert patch_entry.order == 5

    def test_default_order_is_zero(self) -> None:
        reset_registry()

        @db_patch
        async def unordered_patch() -> None:
            pass

        patch_entry = [p for p in get_registry().get_all() if p.name == "unordered_patch"][0]
        assert patch_entry.order == 0


class TestPatchRegistrySorting:
    """Test that patches preserve registration order."""

    def test_preserves_registration_order(self) -> None:
        registry = PatchRegistry()
        registry._patches = [
            PatchEntry(
                app="blog",
                module="blog",
                name="zebra",
                func=AsyncMock(),
                order=0,
                post_migrate=True,
            ),
            PatchEntry(
                app="blog",
                module="blog",
                name="alpha",
                func=AsyncMock(),
                order=0,
                post_migrate=True,
            ),
            PatchEntry(
                app="blog",
                module="blog",
                name="mid",
                func=AsyncMock(),
                order=1,
                post_migrate=True,
            ),
        ]

        sorted_patches = registry.get_sorted()
        assert sorted_patches[0].name == "zebra"
        assert sorted_patches[1].name == "alpha"
        assert sorted_patches[2].name == "mid"

    def test_filters_by_post_migrate_phase(self) -> None:
        registry = PatchRegistry()
        registry._patches = [
            PatchEntry(
                app="blog",
                module="blog",
                name="pre",
                func=AsyncMock(),
                order=0,
                post_migrate=False,
            ),
            PatchEntry(
                app="blog",
                module="blog",
                name="post",
                func=AsyncMock(),
                order=0,
                post_migrate=True,
            ),
        ]

        post_patches = registry.get_sorted(post_migrate=True)
        assert len(post_patches) == 1
        assert post_patches[0].name == "post"

        pre_patches = registry.get_sorted(post_migrate=False)
        assert len(pre_patches) == 1
        assert pre_patches[0].name == "pre"

    def test_empty_registry_returns_empty_list(self) -> None:
        reset_registry()
        registry = PatchRegistry()
        assert registry.get_all() == []
        assert registry.get_sorted() == []
