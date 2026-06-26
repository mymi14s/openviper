"""Unit tests for the patch runner."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from openviper.db.patches.decorator import PatchEntry, PatchRegistry
from openviper.db.patches.runner import (
    get_patch_label,
    get_phase_title,
    run_patches,
)


class TestPatchRunnerExecution:
    """Test the patch execution runner."""

    @pytest.mark.asyncio
    async def test_run_patches_executes_unapplied_patch(self) -> None:
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

        with (
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
            applied = await run_patches(post_migrate=True)

        assert len(applied) == 1
        mock_func.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_patches_skips_already_applied_patch(self) -> None:
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

        with (
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
            applied = await run_patches(post_migrate=True)

        assert applied == []
        mock_func.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_run_patches_executes_in_registration_order(self) -> None:
        call_order: list[str] = []

        async def func_a() -> None:
            call_order.append("a")

        async def func_b() -> None:
            call_order.append("b")

        registry = PatchRegistry()
        registry._patches = [
            PatchEntry(
                app="blog",
                module="blog",
                name="b_patch",
                func=func_b,
                order=1,
                post_migrate=True,
            ),
            PatchEntry(
                app="blog",
                module="blog",
                name="a_patch",
                func=func_a,
                order=0,
                post_migrate=True,
            ),
        ]

        with (
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
            await run_patches(post_migrate=True)

        assert call_order == ["b", "a"]

    @pytest.mark.asyncio
    async def test_run_patches_separates_pre_and_post_phases(self) -> None:
        pre_func = AsyncMock()
        post_func = AsyncMock()
        registry = PatchRegistry()
        registry._patches = [
            PatchEntry(
                app="blog",
                module="blog",
                name="pre_patch",
                func=pre_func,
                order=0,
                post_migrate=False,
            ),
            PatchEntry(
                app="blog",
                module="blog",
                name="post_patch",
                func=post_func,
                order=0,
                post_migrate=True,
            ),
        ]

        with (
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
            pre_applied = await run_patches(post_migrate=False)
            post_applied = await run_patches(post_migrate=True)

        assert len(pre_applied) == 1
        assert len(post_applied) == 1
        pre_func.assert_awaited_once()
        post_func.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_patches_no_patches_returns_empty_list(self) -> None:
        registry = PatchRegistry()

        with (
            patch("openviper.db.patches.runner.get_registry", return_value=registry),
            patch("openviper.db.patches.runner.ensure_patch_table", new_callable=AsyncMock),
            patch(
                "openviper.db.patches.runner.get_applied_patches",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch("openviper.db.patches.runner.record_patch", new_callable=AsyncMock),
        ):
            applied = await run_patches(post_migrate=True)

        assert applied == []

    @pytest.mark.asyncio
    async def test_run_patches_records_applied_patch_in_database(self) -> None:
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

        with (
            patch("openviper.db.patches.runner.get_registry", return_value=registry),
            patch("openviper.db.patches.runner.ensure_patch_table", new_callable=AsyncMock),
            patch(
                "openviper.db.patches.runner.get_applied_patches",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch(
                "openviper.db.patches.runner.record_patch", new_callable=AsyncMock
            ) as mock_record,
            patch("builtins.print"),
        ):
            await run_patches(post_migrate=True)

        mock_record.assert_awaited_once_with("blog", "my_patch", "post", db_alias="default")


class TestPatchRunnerOutput:
    """Test the patch runner console output."""

    @pytest.mark.asyncio
    async def test_run_patches_prints_executing_and_success_lines(self) -> None:
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

        with (
            patch("openviper.db.patches.runner.get_registry", return_value=registry),
            patch("openviper.db.patches.runner.ensure_patch_table", new_callable=AsyncMock),
            patch(
                "openviper.db.patches.runner.get_applied_patches",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch("openviper.db.patches.runner.record_patch", new_callable=AsyncMock),
            patch("builtins.print") as mock_print,
        ):
            await run_patches(post_migrate=True)

        printed = " ".join(str(c) for c in mock_print.call_args_list)
        assert "Executing" in printed
        assert "Success" in printed
        assert "my_patch" in printed

    @pytest.mark.asyncio
    async def test_run_patches_prints_phase_title_and_complete(self) -> None:
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

        with (
            patch("openviper.db.patches.runner.get_registry", return_value=registry),
            patch("openviper.db.patches.runner.ensure_patch_table", new_callable=AsyncMock),
            patch(
                "openviper.db.patches.runner.get_applied_patches",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch("openviper.db.patches.runner.record_patch", new_callable=AsyncMock),
            patch("builtins.print") as mock_print,
        ):
            await run_patches(post_migrate=True)

        printed = " ".join(str(c) for c in mock_print.call_args_list)
        assert "Post Migrate Patches" in printed
        assert "Complete" in printed

    @pytest.mark.asyncio
    async def test_run_patches_prints_docstring_when_present(self) -> None:
        async def patch_with_doc() -> None:
            """Update items with default value."""
            pass

        registry = PatchRegistry()
        registry._patches = [
            PatchEntry(
                app="blog",
                module="blog",
                name="update_defaults",
                func=patch_with_doc,
                order=0,
                post_migrate=True,
            ),
        ]

        with (
            patch("openviper.db.patches.runner.get_registry", return_value=registry),
            patch("openviper.db.patches.runner.ensure_patch_table", new_callable=AsyncMock),
            patch(
                "openviper.db.patches.runner.get_applied_patches",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch("openviper.db.patches.runner.record_patch", new_callable=AsyncMock),
            patch("builtins.print") as mock_print,
        ):
            await run_patches(post_migrate=True)

        printed = " ".join(str(c) for c in mock_print.call_args_list)
        assert "Info: Update items with default value." in printed

    @pytest.mark.asyncio
    async def test_run_patches_omits_info_line_when_no_docstring(self) -> None:
        async def patch_no_doc() -> None:
            pass

        registry = PatchRegistry()
        registry._patches = [
            PatchEntry(
                app="blog",
                module="blog",
                name="no_doc_patch",
                func=patch_no_doc,
                order=0,
                post_migrate=True,
            ),
        ]

        with (
            patch("openviper.db.patches.runner.get_registry", return_value=registry),
            patch("openviper.db.patches.runner.ensure_patch_table", new_callable=AsyncMock),
            patch(
                "openviper.db.patches.runner.get_applied_patches",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch("openviper.db.patches.runner.record_patch", new_callable=AsyncMock),
            patch("builtins.print") as mock_print,
        ):
            await run_patches(post_migrate=True)

        printed = " ".join(str(c) for c in mock_print.call_args_list)
        assert "Info:" not in printed


class TestPatchRunnerHelpers:
    """Test helper functions."""

    def test_get_phase_title_post_migrate(self) -> None:
        assert get_phase_title(post_migrate=True) == "Post Migrate Patches"

    def test_get_phase_title_pre_migrate(self) -> None:
        assert get_phase_title(post_migrate=False) == "Pre Migrate Patches"

    def test_get_patch_label_uses_app_and_name(self) -> None:
        async def my_func() -> None:
            pass

        entry = PatchEntry(
            app="blog",
            module="blog.patches.v1",
            name="my_func",
            func=my_func,
            order=0,
            post_migrate=True,
        )
        label = get_patch_label(entry)
        assert label == "blog.patches.v1.my_func"
