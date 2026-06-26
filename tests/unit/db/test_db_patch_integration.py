"""Integration tests for the @db_patch system.

Tests the full flow: schema sync runs pre_migrate patches, then
schema sync, then post_migrate patches, and subsequent runs skip
already-applied patches.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from openviper.db.patches.decorator import PatchEntry, PatchRegistry
from openviper.db.schemas.sync import SchemaSync


class TestPatchIntegrationWithSync:
    """Test that patches integrate with SchemaSync.sync()."""

    @pytest.mark.asyncio
    async def test_sync_runs_pre_migrate_patches_before_schema_sync(self) -> None:
        call_order: list[str] = []

        async def mock_pre_patch() -> None:
            call_order.append("pre_patch")

        registry = PatchRegistry()
        registry._patches = [
            PatchEntry(
                app="blog",
                module="blog",
                name="pre_patch",
                func=mock_pre_patch,
                order=0,
                post_migrate=False,
            ),
        ]

        desired_state = {
            "test_table": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "primary_key": True, "default": None},
                ],
                "indexes": [],
                "unique_together": [],
            }
        }

        with (
            patch("openviper.db.schemas.sync.discover_json_schemas", return_value=desired_state),
            patch(
                "openviper.db.schemas.sync.introspect_db_schema",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("openviper.db.schemas.sync.diff_states", return_value=[]),
            patch("openviper.db.patches.runner.get_registry", return_value=registry),
            patch("openviper.db.patches.runner.ensure_patch_table", new_callable=AsyncMock),
            patch(
                "openviper.db.patches.runner.get_applied_patches",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch("openviper.db.patches.runner.record_patch", new_callable=AsyncMock),
            patch("builtins.print"),
        ):
            sync = SchemaSync(resolved_apps={"blog": "/tmp/blog"})
            await sync.sync(verbose=False)

        assert "pre_patch" in call_order

    @pytest.mark.asyncio
    async def test_sync_runs_post_migrate_patches_after_schema_sync(self) -> None:
        call_order: list[str] = []

        async def mock_post_patch() -> None:
            call_order.append("post_patch")

        registry = PatchRegistry()
        registry._patches = [
            PatchEntry(
                app="blog",
                module="blog",
                name="post_patch",
                func=mock_post_patch,
                order=0,
                post_migrate=True,
            ),
        ]

        desired_state = {
            "test_table": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "primary_key": True, "default": None},
                ],
                "indexes": [],
                "unique_together": [],
            }
        }

        with (
            patch("openviper.db.schemas.sync.discover_json_schemas", return_value=desired_state),
            patch(
                "openviper.db.schemas.sync.introspect_db_schema",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("openviper.db.schemas.sync.diff_states", return_value=[]),
            patch("openviper.db.patches.runner.get_registry", return_value=registry),
            patch("openviper.db.patches.runner.ensure_patch_table", new_callable=AsyncMock),
            patch(
                "openviper.db.patches.runner.get_applied_patches",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch("openviper.db.patches.runner.record_patch", new_callable=AsyncMock),
            patch("builtins.print"),
        ):
            sync = SchemaSync(resolved_apps={"blog": "/tmp/blog"})
            await sync.sync(verbose=False)

        assert "post_patch" in call_order

    @pytest.mark.asyncio
    async def test_sync_skips_already_applied_patches(self) -> None:
        mock_func = AsyncMock()
        registry = PatchRegistry()
        registry._patches = [
            PatchEntry(
                app="blog",
                module="blog",
                name="my_patch",
                func=mock_func,
                order=0,
                post_migrate=True,
            ),
        ]

        desired_state = {
            "test_table": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "primary_key": True, "default": None},
                ],
                "indexes": [],
                "unique_together": [],
            }
        }

        with (
            patch("openviper.db.schemas.sync.discover_json_schemas", return_value=desired_state),
            patch(
                "openviper.db.schemas.sync.introspect_db_schema",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("openviper.db.schemas.sync.diff_states", return_value=[]),
            patch("openviper.db.patches.runner.get_registry", return_value=registry),
            patch("openviper.db.patches.runner.ensure_patch_table", new_callable=AsyncMock),
            patch(
                "openviper.db.patches.runner.get_applied_patches",
                new_callable=AsyncMock,
                return_value={("blog", "my_patch", "post")},
            ),
            patch("openviper.db.patches.runner.record_patch", new_callable=AsyncMock),
            patch("builtins.print"),
        ):
            sync = SchemaSync(resolved_apps={"blog": "/tmp/blog"})
            await sync.sync(verbose=False)

        mock_func.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sync_runs_pre_patches_before_post_patches(self) -> None:
        call_order: list[str] = []

        async def mock_pre() -> None:
            call_order.append("pre")

        async def mock_post() -> None:
            call_order.append("post")

        registry = PatchRegistry()
        registry._patches = [
            PatchEntry(
                app="blog",
                module="blog",
                name="post_patch",
                func=mock_post,
                order=0,
                post_migrate=True,
            ),
            PatchEntry(
                app="blog",
                module="blog",
                name="pre_patch",
                func=mock_pre,
                order=0,
                post_migrate=False,
            ),
        ]

        desired_state = {
            "test_table": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "primary_key": True, "default": None},
                ],
                "indexes": [],
                "unique_together": [],
            }
        }

        with (
            patch("openviper.db.schemas.sync.discover_json_schemas", return_value=desired_state),
            patch(
                "openviper.db.schemas.sync.introspect_db_schema",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("openviper.db.schemas.sync.diff_states", return_value=[]),
            patch("openviper.db.patches.runner.get_registry", return_value=registry),
            patch("openviper.db.patches.runner.ensure_patch_table", new_callable=AsyncMock),
            patch(
                "openviper.db.patches.runner.get_applied_patches",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch("openviper.db.patches.runner.record_patch", new_callable=AsyncMock),
            patch("builtins.print"),
        ):
            sync = SchemaSync(resolved_apps={"blog": "/tmp/blog"})
            await sync.sync(verbose=False)

        assert call_order.index("pre") < call_order.index("post")

    @pytest.mark.asyncio
    async def test_sync_with_no_patches_completes_without_error(self) -> None:
        registry = PatchRegistry()

        desired_state = {
            "test_table": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "primary_key": True, "default": None},
                ],
                "indexes": [],
                "unique_together": [],
            }
        }

        with (
            patch("openviper.db.schemas.sync.discover_json_schemas", return_value=desired_state),
            patch(
                "openviper.db.schemas.sync.introspect_db_schema",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("openviper.db.schemas.sync.diff_states", return_value=[]),
            patch("openviper.db.patches.runner.get_registry", return_value=registry),
            patch("openviper.db.patches.runner.ensure_patch_table", new_callable=AsyncMock),
            patch(
                "openviper.db.patches.runner.get_applied_patches",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch("openviper.db.patches.runner.record_patch", new_callable=AsyncMock),
            patch("builtins.print"),
        ):
            sync = SchemaSync(resolved_apps={"blog": "/tmp/blog"})
            result = await sync.sync(verbose=False)

        assert result == []
