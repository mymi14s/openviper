"""Additional branch tests for openviper.db.models."""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.db.fields import CharField, DateTimeField, ForeignKey, LazyFK
from openviper.db.models import Model, QuerySet, TraversalLookup
from openviper.exceptions import FieldError


class BranchNote(Model):
    title = CharField(max_length=64)

    class Meta:
        table_name = "branch_note"


class BulkItem(Model):
    name = CharField()

    class Meta:
        table_name = "bulk_items"


class Author(Model):
    name = CharField()

    class Meta:
        table_name = "br_authors"


class Post(Model):
    title = CharField()
    author = ForeignKey(Author, on_delete="CASCADE")

    class Meta:
        table_name = "br_posts"


class FKModel(Model):
    ref = ForeignKey(Author, on_delete="CASCADE")

    class Meta:
        table_name = "fk_model_val"


class TimestampModel(Model):
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        table_name = "ts_model"


class ColumnAliasModel(Model):
    """Model whose field has a db_column different from the attribute name."""

    score = CharField(null=False, db_column="score_value")

    class Meta:
        table_name = "col_alias_model"


# ── delete / refresh ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_model_delete_with_ignore_permissions_propagates_flag():
    note = BranchNote(id=9, title="a")

    with patch(
        "openviper.db.models.execute_delete_instance", new_callable=AsyncMock
    ) as mock_delete:
        await note.delete(ignore_permissions=True)

    mock_delete.assert_awaited_once_with(note, ignore_permissions=True)


@pytest.mark.asyncio
async def test_refresh_from_db_updates_all_fields_and_snapshot():
    note = BranchNote(id=1, title="before")
    fresh = BranchNote(id=1, title="after")

    with patch.object(BranchNote.objects, "get", new_callable=AsyncMock, return_value=fresh):
        await note.refresh_from_db()

    assert note.title == "after"
    assert note.has_changed is False


@pytest.mark.asyncio
async def test_delete_stops_when_on_delete_hook_raises():
    note = BranchNote(id=4, title="x")

    async def failing_hook():
        raise RuntimeError("stop-delete")

    note.on_delete = failing_hook

    with patch(
        "openviper.db.models.execute_delete_instance", new_callable=AsyncMock
    ) as mock_delete:
        with pytest.raises(RuntimeError, match="stop-delete"):
            await note.delete()

    mock_delete.assert_not_awaited()


# ── bulk_create / bulk_update ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_create_ignore_permissions_executes():
    mock_conn = AsyncMock()
    mock_begin_ctx = AsyncMock()
    mock_begin_ctx.__aenter__.return_value = mock_conn

    with (
        patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        patch("openviper.db.models._begin", return_value=mock_begin_ctx),
    ):
        items = [BulkItem(name="a"), BulkItem(name="b")]
        result = await BulkItem.objects.bulk_create(items, ignore_permissions=True)

    assert len(result) == 2
    assert mock_conn.execute.called


@pytest.mark.asyncio
async def test_bulk_create_with_batch_size():
    mock_conn = AsyncMock()
    mock_begin_ctx = AsyncMock()
    mock_begin_ctx.__aenter__.return_value = mock_conn

    with (
        patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        patch("openviper.db.models._begin", return_value=mock_begin_ctx),
    ):
        items = [BulkItem(name=f"item{i}") for i in range(5)]
        await BulkItem.objects.bulk_create(items, batch_size=2)

    # With batch_size=2 and 5 items, execute called 3 times
    assert mock_conn.execute.call_count == 3


@pytest.mark.asyncio
async def test_bulk_update_ignore_permissions_executes():
    with (
        patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        patch(
            "openviper.db.models.execute_bulk_update", new_callable=AsyncMock, return_value=2
        ) as mock_update,
    ):
        items = [BulkItem(name="a")]
        total = await BulkItem.objects.bulk_update(items, fields=["name"], ignore_permissions=True)

    assert total == 2
    mock_update.assert_awaited_once()


# ── Manager._trigger_bulk_event ───────────────────────────────────────────────


def test_trigger_bulk_event_with_dispatcher():
    mock_dispatcher = MagicMock()
    with (
        patch("openviper.db.events.get_dispatcher", return_value=mock_dispatcher),
        patch("openviper.db.events._dispatch_decorator_handlers"),
    ):
        BulkItem.objects._trigger_bulk_event(
            "myapp.BulkItem", "pre_bulk_create", []
        )  # noqa: SLF001
    mock_dispatcher.trigger.assert_called_once()


def test_trigger_bulk_event_without_dispatcher():
    with (
        patch("openviper.db.events.get_dispatcher", return_value=None),
        patch("openviper.db.events._dispatch_decorator_handlers") as mock_dec,
    ):
        BulkItem.objects._trigger_bulk_event(
            "myapp.BulkItem", "pre_bulk_create", []
        )  # noqa: SLF001
    mock_dec.assert_called_once()


def test_trigger_bulk_event_exception_suppressed():
    with patch("openviper.db.events.get_dispatcher", side_effect=RuntimeError("boom")):
        BulkItem.objects._trigger_bulk_event(
            "myapp.BulkItem", "pre_bulk_create", []
        )  # noqa: SLF001


# ── QuerySet all() with ignore_permissions ────────────────────────────────────


@pytest.mark.asyncio
async def test_queryset_all_ignore_permissions_executes():
    qs = QuerySet(BranchNote)
    qs._ignore_permissions = True  # noqa: SLF001

    with (
        patch(
            "openviper.db.models.execute_select",
            new_callable=AsyncMock,
            return_value=[{"id": 1, "title": "x"}],
        ),
        patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
    ):
        results = await qs.all()

    assert len(results) == 1


# ── QuerySet count/exists/delete/update with ignore_permissions ───────────────


@pytest.mark.asyncio
async def test_queryset_count_ignore_permissions():
    qs = QuerySet(BranchNote)
    qs._ignore_permissions = True  # noqa: SLF001

    with (
        patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        patch("openviper.db.models.execute_count", new_callable=AsyncMock, return_value=3),
    ):
        result = await qs.count()

    assert result == 3


@pytest.mark.asyncio
async def test_queryset_exists_ignore_permissions():
    qs = QuerySet(BranchNote)
    qs._ignore_permissions = True  # noqa: SLF001

    with (
        patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        patch("openviper.db.models.execute_exists", new_callable=AsyncMock, return_value=True),
    ):
        result = await qs.exists()

    assert result is True


@pytest.mark.asyncio
async def test_queryset_delete_ignore_permissions():
    qs = QuerySet(BranchNote)
    qs._ignore_permissions = True  # noqa: SLF001

    with (
        patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        patch("openviper.db.models.execute_delete", new_callable=AsyncMock, return_value=1),
    ):
        result = await qs.delete()

    assert result == 1


@pytest.mark.asyncio
async def test_queryset_update_ignore_permissions():
    qs = QuerySet(BranchNote)
    qs._ignore_permissions = True  # noqa: SLF001

    with (
        patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        patch("openviper.db.models.execute_update", new_callable=AsyncMock, return_value=1),
    ):
        result = await qs.update(title="new")

    assert result == 1


@pytest.mark.asyncio
async def test_queryset_values_ignore_permissions():
    qs = QuerySet(BranchNote)
    qs._ignore_permissions = True  # noqa: SLF001

    with (
        patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        patch(
            "openviper.db.models.execute_values",
            new_callable=AsyncMock,
            return_value=[{"title": "x"}],
        ),
    ):
        result = await qs.values("title")

    assert result == [{"title": "x"}]


# ── iterator / batch last-chunk break ────────────────────────────────────────


@pytest.mark.asyncio
async def test_iterator_breaks_on_partial_chunk():
    """iterator() breaks when chunk size < chunk_size (last page)."""
    qs = QuerySet(BranchNote)
    calls = []
    with (
        patch("openviper.db.models.execute_select", new_callable=AsyncMock) as mock_exec,
        patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
    ):
        mock_exec.return_value = [{"id": 1, "title": "a"}, {"id": 2, "title": "b"}]
        async for item in qs.iterator(chunk_size=10):
            calls.append(item)

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_batch_breaks_on_partial_chunk():
    """batch() breaks when chunk size < size (last page)."""
    qs = QuerySet(BranchNote)
    batches = []
    with (
        patch("openviper.db.models.execute_select", new_callable=AsyncMock) as mock_exec,
        patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
    ):
        mock_exec.return_value = [{"id": 1, "title": "a"}]
        async for batch in qs.batch(size=10):
            batches.append(batch)

    assert len(batches) == 1
    assert len(batches[0]) == 1


# ── _hydrate_select_related: None-path and instance-path ─────────────────────


def test_hydrate_select_related_sets_none_when_all_values_null():
    qs = QuerySet(Post)
    qs._select_related = ["author"]  # noqa: SLF001

    instance = Post.__new__(Post)
    instance._relation_cache = None  # noqa: SLF001
    instance._previous_state = {}  # noqa: SLF001

    row = {"id": 1, "title": "Test", "author__id": None, "author__name": None}

    Post._fields["author"].resolve_target = lambda: Author  # noqa: SLF001
    qs._hydrate_select_related(instance, row)  # noqa: SLF001

    assert instance._get_related("author") is None  # noqa: SLF001


def test_hydrate_select_related_sets_instance_when_values_present():
    qs = QuerySet(Post)
    qs._select_related = ["author"]  # noqa: SLF001

    instance = Post.__new__(Post)
    instance._relation_cache = None  # noqa: SLF001
    instance._previous_state = {}  # noqa: SLF001

    row = {"id": 1, "title": "Test", "author__id": 5, "author__name": "Alice"}

    Post._fields["author"].resolve_target = lambda: Author  # noqa: SLF001
    qs._hydrate_select_related(instance, row)  # noqa: SLF001

    related = instance._get_related("author")  # noqa: SLF001
    assert related is not None
    assert related.name == "Alice"


def test_hydrate_select_related_skips_unknown_field():
    qs = QuerySet(Post)
    qs._select_related = ["nonexistent_field"]  # noqa: SLF001

    instance = Post.__new__(Post)
    instance._relation_cache = None  # noqa: SLF001
    instance._previous_state = {}  # noqa: SLF001

    row = {"id": 1, "title": "Test"}
    qs._hydrate_select_related(instance, row)  # noqa: SLF001


# ── _from_row / _from_row_fast ────────────────────────────────────────────────


def test_from_row_col_name_in_row():
    """Field's column_name is in the row (e.g. 'author_id')."""
    row = {"id": 1, "title": "Hello", "author_id": 42}
    p = Post._from_row(row)  # noqa: SLF001
    assert p.title == "Hello"


def test_from_row_fast_fk_uses_col_name_key():
    """ForeignKey in _from_row_fast stores under column_name key."""
    row = {"id": 1, "title": "Hello", "author_id": 99}
    p = Post._from_row_fast(row)  # noqa: SLF001
    assert p.__dict__.get("author_id") == 99


# ── validate: FK alias skip branch ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_fk_alias_set_skips_null_check():
    """FK value None but column_name alias (ref_id) is set — FK field should pass."""
    obj = FKModel.__new__(FKModel)
    obj._previous_state = {}  # noqa: SLF001
    obj._relation_cache = None  # noqa: SLF001
    obj.ref = None
    obj.ref_id = 5  # alias is set
    try:
        await obj.validate()
    except ValueError as e:
        assert "ref" not in str(e)


# ── _apply_auto_fields ────────────────────────────────────────────────────────


def test_apply_auto_fields_auto_now_always_sets():
    obj = TimestampModel()
    obj.updated_at = None
    obj._apply_auto_fields()  # noqa: SLF001
    assert obj.updated_at is not None


def test_apply_auto_fields_auto_now_add_skips_if_set():
    obj = TimestampModel()
    existing_time = datetime.datetime(2020, 1, 1)
    obj.created_at = existing_time
    obj._apply_auto_fields()  # noqa: SLF001
    assert obj.created_at == existing_time


# ── _to_dict FK path ──────────────────────────────────────────────────────────


def test_to_dict_fk_uses_column_name():
    p = Post(title="Hello")
    p.__dict__["author_id"] = 42
    d = p._to_dict()  # noqa: SLF001
    assert "author" in d
    assert d["author"] == 42


# ── validation soft-removed skip ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_skips_soft_removed_column():
    """Column in soft_removed set is not validated."""
    with patch("openviper.db.models.get_soft_removed_columns", return_value={"title"}):
        note = BranchNote(id=1, title=None)
        await note.validate()


# ── TraversalLookup: non-model intermediate raises FieldError ─────────────────


def test_traversal_lookup_non_model_intermediate_raises():

    class NotAModel:
        __name__ = "NotAModel"

    original = Post._fields["author"].resolve_target
    Post._fields["author"].resolve_target = lambda: NotAModel
    try:
        with pytest.raises(FieldError, match="not a Model"):
            TraversalLookup("author__something__deep", Post)
    finally:
        Post._fields["author"].resolve_target = original


# ── QuerySet.all(): select_related pre-compute branches ──────────────────────


@pytest.mark.asyncio
async def test_all_select_related_field_none_skips():
    """Field not in _fields → field is None → continue (line 859)."""
    qs = QuerySet(Post)
    qs._select_related = ["nonexistent_field"]

    with (
        patch(
            "openviper.db.models.execute_select",
            new_callable=AsyncMock,
            return_value=[{"id": 1, "title": "x"}],
        ),
        patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
    ):
        results = await qs.all()

    assert len(results) == 1


@pytest.mark.asyncio
async def test_all_select_related_resolved_cls_none_skips():
    """resolve_target() returns None → continue (line 862)."""
    qs = QuerySet(Post)
    qs._select_related = ["author"]

    original = Post._fields["author"].resolve_target
    Post._fields["author"].resolve_target = lambda: None
    try:
        with (
            patch(
                "openviper.db.models.execute_select",
                new_callable=AsyncMock,
                return_value=[{"id": 1, "title": "x", "author_id": None}],
            ),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            results = await qs.all()
        assert len(results) == 1
    finally:
        Post._fields["author"].resolve_target = original


# ── QuerySet.aggregate(): ignore_permissions path ────────────────────────────


@pytest.mark.asyncio
async def test_aggregate_with_ignore_permissions_sets_and_resets_token():
    qs = QuerySet(BranchNote)
    qs._ignore_permissions = True

    with (
        patch(
            "openviper.db.models.execute_aggregate",
            new_callable=AsyncMock,
            return_value={"total": 5},
        ),
        patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
    ):
        result = await qs.aggregate(total="Count('id')")

    assert result == {"total": 5}


# ── iterator / batch / id_batch: empty-chunk early break ─────────────────────


@pytest.mark.asyncio
async def test_iterator_empty_chunk_breaks_immediately():
    qs = QuerySet(BranchNote)
    calls = []
    with (
        patch("openviper.db.models.execute_select", new_callable=AsyncMock, return_value=[]),
        patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
    ):
        async for item in qs.iterator(chunk_size=10):
            calls.append(item)
    assert calls == []


@pytest.mark.asyncio
async def test_batch_empty_chunk_breaks_immediately():
    qs = QuerySet(BranchNote)
    batches = []
    with (
        patch("openviper.db.models.execute_select", new_callable=AsyncMock, return_value=[]),
        patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
    ):
        async for batch in qs.batch(size=10):
            batches.append(batch)
    assert batches == []


@pytest.mark.asyncio
async def test_id_batch_empty_chunk_breaks_immediately():
    qs = QuerySet(BranchNote)
    batches = []
    with (
        patch("openviper.db.models.execute_select", new_callable=AsyncMock, return_value=[]),
        patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
    ):
        async for batch in qs.id_batch(size=10):
            batches.append(batch)
    assert batches == []


# ── _hydrate_select_related: resolved_cls None skips (line 1157) ──────────────


def test_hydrate_select_related_resolved_cls_none_skips():
    qs = QuerySet(Post)
    qs._select_related = ["author"]

    instance = Post.__new__(Post)
    instance._relation_cache = None
    instance._previous_state = {}

    row = {"id": 1, "title": "Test", "author__id": 5, "author__name": "X"}

    original = Post._fields["author"].resolve_target
    Post._fields["author"].resolve_target = lambda: None
    try:
        qs._hydrate_select_related(instance, row)
        # No related set because related_cls is None
        assert instance._get_related("author") is None
    finally:
        Post._fields["author"].resolve_target = original


# ── _hydrate_select_related_fast: None path (line 1179) ──────────────────────


def test_hydrate_select_related_fast_sets_none_when_all_values_null():
    qs = QuerySet(Post)

    instance = Post.__new__(Post)
    instance._relation_cache = None
    instance._previous_state = {}

    sr_mappings = {"author": (Author, [("author__id", "id"), ("author__name", "name")])}
    row = {"id": 1, "title": "Test", "author__id": None, "author__name": None}

    qs._hydrate_select_related_fast(instance, row, sr_mappings)
    assert instance._get_related("author") is None


# ── _do_prefetch_related: skip branches ──────────────────────────────────────


@pytest.mark.asyncio
async def test_do_prefetch_related_field_none_skips():
    """Field not in _fields → field is None → continue (line 1198)."""
    qs = QuerySet(BranchNote)
    qs._prefetch_related = ["nonexistent_field"]
    # Should not raise
    await qs._do_prefetch_related([])


@pytest.mark.asyncio
async def test_do_prefetch_related_related_cls_none_skips():
    """resolve_target() → None → continue (line 1201)."""
    qs = QuerySet(Post)
    qs._prefetch_related = ["author"]

    original = Post._fields["author"].resolve_target
    Post._fields["author"].resolve_target = lambda: None
    try:
        p = Post.__new__(Post)
        p.__dict__["author_id"] = 5
        p._relation_cache = None
        await qs._do_prefetch_related([p])
    finally:
        Post._fields["author"].resolve_target = original


@pytest.mark.asyncio
async def test_do_prefetch_related_no_fk_ids_continues_and_no_tasks_returns():
    """No valid int fk_ids → continue; no tasks → return early (lines 1217, 1225)."""
    qs = QuerySet(Post)
    qs._prefetch_related = ["author"]

    p = Post.__new__(Post)
    p.__dict__["author_id"] = None  # Not int → not collected
    p._relation_cache = None

    with (
        patch("openviper.db.models.execute_select", new_callable=AsyncMock) as mock_exec,
        patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
    ):
        await qs._do_prefetch_related([p])
        # execute_select should NOT be called (no tasks)
    mock_exec.assert_not_awaited()


@pytest.mark.asyncio
async def test_do_prefetch_related_lazy_fk_ids_collected():
    """LazyFK with int fk_id is collected (lines 1213-1214)."""

    qs = QuerySet(Post)
    qs._prefetch_related = ["author"]

    fk_field = Post._fields["author"]
    post = Post.__new__(Post)
    post._relation_cache = None
    post._previous_state = {}
    lazy = LazyFK(fk_field=fk_field, instance=post, fk_id=99)
    post.__dict__["author_id"] = lazy

    with (
        patch(
            "openviper.db.models.execute_select",
            new_callable=AsyncMock,
            return_value=[{"id": 99, "name": "Bob"}],
        ),
        patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
    ):
        await qs._do_prefetch_related([post])


@pytest.mark.asyncio
async def test_do_prefetch_related_lazy_fk_result_mapping():
    """LazyFK result_map lookup (lines 1243-1245)."""

    qs = QuerySet(Post)
    qs._prefetch_related = ["author"]

    fk_field = Post._fields["author"]
    post = Post.__new__(Post)
    post._relation_cache = None
    post._previous_state = {}
    lazy = LazyFK(fk_field=fk_field, instance=post, fk_id=7)
    post.__dict__["author_id"] = lazy

    with (
        patch(
            "openviper.db.models.execute_select",
            new_callable=AsyncMock,
            return_value=[{"id": 7, "name": "Alice"}],
        ),
        patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
    ):
        await qs._do_prefetch_related([post])

    related = post._get_related("author")
    assert related is not None
    assert related.name == "Alice"


# ── validate(): FK alias continue (line 1524) ────────────────────────────────


@pytest.mark.asyncio
async def test_validate_fk_alias_set_skips_null_check_async():
    """Field with db_column alias set → continue (line 1524).

    ColumnAliasModel.score has null=False but db_column="score_value".
    When score (the field value) is None but score_value (the column alias) is
    non-None, validate() should hit the ``continue`` at line 1524 and not raise.
    """
    obj = ColumnAliasModel.__new__(ColumnAliasModel)
    obj._previous_state = {}
    obj._relation_cache = None  # noqa: SLF001
    # CharField is a non-data descriptor so instance __dict__ wins for both names.
    obj.__dict__["score"] = None  # field value is None → would fail null check
    obj.__dict__["score_value"] = 5  # column alias is set → triggers continue

    with (
        patch("openviper.db.models._load_soft_removed_columns", new_callable=AsyncMock),
        patch("openviper.db.models.get_soft_removed_columns", return_value=set()),
    ):
        # Should not raise: score is None but score_value alias is set → continue
        await obj.validate()


@pytest.mark.asyncio
async def test_validate_skips_auto_now_datetime_fields():
    """DateTimeField with auto_now/auto_now_add → continue (line 1509)."""
    obj = TimestampModel.__new__(TimestampModel)
    obj._previous_state = {}
    obj._relation_cache = None
    obj.__dict__["created_at"] = None
    obj.__dict__["updated_at"] = None

    with (
        patch("openviper.db.models._load_soft_removed_columns", new_callable=AsyncMock),
        patch("openviper.db.models.get_soft_removed_columns", return_value=set()),
    ):
        # auto_now and auto_now_add fields should be skipped in validation
        await obj.validate()


# ── _from_row: name-in-row fallback (lines 1595-1596) ────────────────────────


def test_from_row_uses_field_name_when_col_name_absent():
    """col_name not in row but field name is → use field name (line 1596)."""
    # Use "author" key (the field name) instead of "author_id" (the column name)
    row = {"id": 1, "title": "Hello", "author": 42}
    p = Post._from_row(row)
    assert p.title == "Hello"
    # The author value should be loaded from "author" key
    assert p.__dict__.get("author_id") == 42 or p.__dict__.get("author") == 42


# ── _from_row_fast: name-in-row fallback (line 1625) ─────────────────────────


def test_from_row_fast_uses_field_name_when_col_name_absent():
    """col_name not in row but field name is → use field name (line 1625)."""
    row = {"id": 1, "title": "Hello", "author": 42}
    p = Post._from_row_fast(row)
    assert p.title == "Hello"
    # "author" key used since "author_id" not in row
    assert p.__dict__.get("author_id") == 42 or p.__dict__.get("author") == 42
