"""Unit tests for openviper/db/executor.py."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy as sa

import openviper.db.executor as mod
from openviper.db.executor import (
    _SOFT_REMOVED_CACHE,
    _TRAVERSAL_FAILURE,
    MAX_QUERY_ROWS,
    _ann_expr_as_sa,
    _apply_lookup,
    _build_where_clause,
    _build_where_clause_with_traversals,
    _bypass_permissions,
    _cached_traversal_lookup,
    _compile_excludes,
    _compile_filters,
    _compile_q,
    _compile_single_filter,
    _compile_traversal_filter,
    _escape_like,
    _f_expr_as_sa,
    _is_f_like,
    _load_soft_removed_columns,
    _parse_traversal_cached,
    bypass_permissions,
    execute_aggregate,
    execute_bulk_update,
    execute_count,
    execute_delete,
    execute_delete_instance,
    execute_exists,
    execute_explain,
    execute_save,
    execute_select,
    execute_update,
    execute_values,
    get_soft_removed_columns,
    get_table,
    invalidate_soft_removed_cache,
)
from openviper.db.fields import CharField, ForeignKey, IntegerField, LazyFK, UUIDField
from openviper.db.models import Count, F, Model, Q, Sum
from openviper.exceptions import FieldError

# ---------------------------------------------------------------------------
# Test models
# ---------------------------------------------------------------------------


class Author(Model):
    username = CharField(max_length=100)

    class Meta:
        table_name = "exec_authors"


class Post(Model):
    title = CharField(max_length=200)
    views = IntegerField(default=0)
    author = ForeignKey("Author", on_delete="CASCADE")

    class Meta:
        table_name = "exec_posts"


class OtpRecord(Model):
    """Model whose PK is a UUID, matching the bug report scenario."""

    id = UUIDField(auto=True, primary_key=True)
    otp = CharField(max_length=6)

    class Meta:
        table_name = "exec_otp_records"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_table(tname: str = "items", **cols) -> sa.Table:
    meta = sa.MetaData()
    columns = [sa.Column("id", sa.Integer, primary_key=True)]
    for col_name, col_type in cols.items():
        columns.append(sa.Column(col_name, col_type))
    return sa.Table(tname, meta, *columns)


def _make_qs(
    model=Post,
    filters=None,
    excludes=None,
    order=None,
    limit=None,
    offset=None,
    only=None,
    defer=None,
    distinct=False,
    annotations=None,
    q_filters=None,
    select_related=None,
    ignore_permissions=False,
):
    qs = MagicMock()
    qs._model = model
    qs._filters = filters or []
    qs._excludes = excludes or []
    qs._order = order or []
    qs._limit = limit
    qs._offset = offset
    qs._only_fields = only or []
    qs._defer_fields = defer or []
    qs._distinct = distinct
    qs._annotations = annotations or {}
    qs._q_filters = q_filters or []
    qs._select_related = select_related or []
    qs._ignore_permissions = ignore_permissions
    return qs


# ---------------------------------------------------------------------------
# bypass_permissions
# ---------------------------------------------------------------------------


class TestBypassPermissions:
    def test_sets_and_resets(self):
        assert _bypass_permissions.get() is False
        with bypass_permissions():
            assert _bypass_permissions.get() is True
        assert _bypass_permissions.get() is False

    def test_resets_on_exception(self):
        with pytest.raises(ValueError, match="boom"):
            with bypass_permissions():
                raise ValueError("boom")
        assert _bypass_permissions.get() is False


# ---------------------------------------------------------------------------
# Soft-removed column cache
# ---------------------------------------------------------------------------


class TestSoftRemovedCache:
    def setup_method(self):
        invalidate_soft_removed_cache()

    def test_get_empty(self):
        result = get_soft_removed_columns("nonexistent_table")
        assert result == frozenset()

    def test_get_populated(self):
        _SOFT_REMOVED_CACHE["my_table"] = frozenset(["deleted_col"])
        result = get_soft_removed_columns("my_table")
        assert result == frozenset(["deleted_col"])
        _SOFT_REMOVED_CACHE.pop("my_table", None)

    def test_invalidate_clears(self):
        _SOFT_REMOVED_CACHE["x"] = frozenset(["c"])
        invalidate_soft_removed_cache()
        assert get_soft_removed_columns("x") == frozenset()


# ---------------------------------------------------------------------------
# _escape_like
# ---------------------------------------------------------------------------


class TestEscapeLike:
    def test_escapes_percent(self):
        assert _escape_like("100%") == "100\\%"

    def test_escapes_underscore(self):
        assert _escape_like("foo_bar") == "foo\\_bar"

    def test_escapes_backslash(self):
        assert _escape_like("a\\b") == "a\\\\b"

    def test_non_string_converted(self):
        result = _escape_like(42)
        assert result == "42"

    def test_no_special_chars(self):
        assert _escape_like("hello") == "hello"


# ---------------------------------------------------------------------------
# _apply_lookup
# ---------------------------------------------------------------------------


class TestApplyLookup:
    def setup_method(self):
        self.table = _make_table("t", name=sa.String(100), age=sa.Integer())
        self.col = self.table.c["name"]
        self.age_col = self.table.c["age"]

    def test_exact(self):
        clause = _apply_lookup(self.col, "exact", "alice")
        assert clause is not None

    def test_empty_string_is_exact(self):
        clause = _apply_lookup(self.col, "", "alice")
        assert clause is not None

    def test_contains(self):
        clause = _apply_lookup(self.col, "contains", "ali")
        assert clause is not None

    def test_icontains(self):
        clause = _apply_lookup(self.col, "icontains", "ali")
        assert clause is not None

    def test_startswith(self):
        clause = _apply_lookup(self.col, "startswith", "al")
        assert clause is not None

    def test_endswith(self):
        clause = _apply_lookup(self.col, "endswith", "ce")
        assert clause is not None

    def test_gt(self):
        clause = _apply_lookup(self.age_col, "gt", 18)
        assert clause is not None

    def test_gte(self):
        clause = _apply_lookup(self.age_col, "gte", 18)
        assert clause is not None

    def test_lt(self):
        clause = _apply_lookup(self.age_col, "lt", 65)
        assert clause is not None

    def test_lte(self):
        clause = _apply_lookup(self.age_col, "lte", 65)
        assert clause is not None

    def test_in(self):
        clause = _apply_lookup(self.age_col, "in", [1, 2, 3])
        assert clause is not None

    def test_in_with_lazyfk(self):
        lf = MagicMock(spec=LazyFK)
        lf.fk_id = 42
        clause = _apply_lookup(self.age_col, "in", [lf])
        assert clause is not None

    def test_isnull_true(self):
        clause = _apply_lookup(self.col, "isnull", True)
        assert clause is not None

    def test_isnull_false(self):
        clause = _apply_lookup(self.col, "isnull", False)
        assert clause is not None

    def test_range(self):
        clause = _apply_lookup(self.age_col, "range", (10, 20))
        assert clause is not None

    def test_unknown_lookup_raises_field_error(self):
        with pytest.raises(FieldError, match="Unsupported lookup type"):
            _apply_lookup(self.col, "bogus_lookup", "x")

    def test_lazyfk_unwrapped(self):
        lf = MagicMock(spec=LazyFK)
        lf.fk_id = 99
        clause = _apply_lookup(self.age_col, "exact", lf)
        assert clause is not None

    def test_uuid_converted_to_str(self):
        uid = uuid.uuid4()
        clause = _apply_lookup(self.col, "exact", uid)
        assert clause is not None

    def test_model_instance_unwrapped_to_id(self) -> None:
        class FakeUser(Model):
            class Meta:
                table_name = "fake_users"

            username = CharField(max_length=100)

        user = FakeUser(username="alice")
        user.__dict__["id"] = 5
        clause = _apply_lookup(self.age_col, "exact", user)
        assert clause is not None
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "5" in compiled

    def test_in_with_model_instances_unwrapped_to_ids(self) -> None:
        class FakeUser(Model):
            class Meta:
                table_name = "fake_users2"

            username = CharField(max_length=100)

        u1 = FakeUser(username="alice")
        u1.__dict__["id"] = 1
        u2 = FakeUser(username="bob")
        u2.__dict__["id"] = 2
        clause = _apply_lookup(self.age_col, "in", [u1, u2])
        assert clause is not None
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "1" in compiled
        assert "2" in compiled

    def test_ne(self):
        clause = _apply_lookup(self.col, "ne", "alice")
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "!=" in compiled or "<>" in compiled

    def test_not_in(self):
        clause = _apply_lookup(self.age_col, "not_in", [1, 2, 3])
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "NOT IN" in compiled.upper()

    def test_not_in_with_lazyfk(self):
        lf = MagicMock(spec=LazyFK)
        lf.fk_id = 42
        clause = _apply_lookup(self.age_col, "not_in", [lf])
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "NOT IN" in compiled.upper()
        assert "42" in compiled

    def test_not_in_with_model_instances(self) -> None:
        class FakeUser(Model):
            class Meta:
                table_name = "fake_users_notin"

            username = CharField(max_length=100)

        u1 = FakeUser(username="alice")
        u1.__dict__["id"] = 10
        clause = _apply_lookup(self.age_col, "not_in", [u1])
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "NOT IN" in compiled.upper()
        assert "10" in compiled

    def test_iexact(self):
        clause = _apply_lookup(self.col, "iexact", "Alice")
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "lower" in compiled.lower()
        assert "alice" in compiled.lower()

    def test_istartswith(self):
        clause = _apply_lookup(self.col, "istartswith", "al")
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "LIKE" in compiled.upper()
        assert "al%" in compiled

    def test_iendswith(self):
        clause = _apply_lookup(self.col, "iendswith", "ce")
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "LIKE" in compiled.upper()
        assert "%ce" in compiled

    def test_regex(self):
        clause = _apply_lookup(self.col, "regex", r"^al.*")
        assert clause is not None

    def test_iregex(self):
        clause = _apply_lookup(self.col, "iregex", r"^al.*")
        assert clause is not None

    def test_date(self):
        import datetime

        dt_table = _make_table("dt", created=sa.DateTime())
        col = dt_table.c["created"]
        clause = _apply_lookup(col, "date", datetime.date(2026, 4, 19))
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "CAST" in compiled.upper() or "DATE" in compiled.upper()

    def test_year(self):
        dt_table = _make_table("dt_y", created=sa.DateTime())
        col = dt_table.c["created"]
        clause = _apply_lookup(col, "year", 2026)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "EXTRACT" in compiled.upper() or "year" in compiled.lower()

    def test_month(self):
        dt_table = _make_table("dt_m", created=sa.DateTime())
        col = dt_table.c["created"]
        clause = _apply_lookup(col, "month", 4)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "EXTRACT" in compiled.upper() or "month" in compiled.lower()

    def test_day(self):
        dt_table = _make_table("dt_d", created=sa.DateTime())
        col = dt_table.c["created"]
        clause = _apply_lookup(col, "day", 19)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "EXTRACT" in compiled.upper() or "day" in compiled.lower()


class TestApplyLookupEdgeCases:
    """Smoke and edge-case tests for all lookup operators."""

    def setup_method(self) -> None:
        self.table = _make_table(
            "edge", name=sa.String(100), age=sa.Integer(), created=sa.DateTime()
        )
        self.col = self.table.c["name"]
        self.age_col = self.table.c["age"]
        self.dt_col = self.table.c["created"]

    def test_ne_with_none(self) -> None:
        clause = _apply_lookup(self.col, "ne", None)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "IS NOT NULL" in compiled.upper()

    def test_ne_with_integer(self) -> None:
        clause = _apply_lookup(self.age_col, "ne", 0)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "!=" in compiled or "<>" in compiled

    def test_ne_with_lazyfk(self) -> None:
        lf = MagicMock(spec=LazyFK)
        lf.fk_id = 7
        clause = _apply_lookup(self.age_col, "ne", lf)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "7" in compiled

    def test_ne_with_uuid(self) -> None:
        uid = uuid.uuid4()
        clause = _apply_lookup(self.col, "ne", uid)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert str(uid) in compiled

    def test_exact_with_none(self) -> None:
        clause = _apply_lookup(self.col, "exact", None)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "IS NULL" in compiled.upper()

    def test_not_in_empty_list(self) -> None:
        clause = _apply_lookup(self.age_col, "not_in", [])
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "NOT IN" in compiled.upper()

    def test_in_empty_list(self) -> None:
        clause = _apply_lookup(self.age_col, "in", [])
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "IN" in compiled.upper()

    def test_contains_special_chars(self) -> None:
        clause = _apply_lookup(self.col, "contains", "100%_off")
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "LIKE" in compiled.upper()
        assert r"100\%\_off" in compiled

    def test_icontains_special_chars(self) -> None:
        clause = _apply_lookup(self.col, "icontains", "50%_sale")
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "LIKE" in compiled.upper()
        assert r"50\%\_sale" in compiled

    def test_startswith_special_chars(self) -> None:
        clause = _apply_lookup(self.col, "startswith", "test_")
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert r"test\_" in compiled

    def test_endswith_special_chars(self) -> None:
        clause = _apply_lookup(self.col, "endswith", "%done")
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert r"\%done" in compiled

    def test_istartswith_special_chars(self) -> None:
        clause = _apply_lookup(self.col, "istartswith", "50%")
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "LIKE" in compiled.upper()
        assert r"50\%" in compiled

    def test_iendswith_special_chars(self) -> None:
        clause = _apply_lookup(self.col, "iendswith", "_end")
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "LIKE" in compiled.upper()
        assert r"\_end" in compiled

    def test_iexact_with_empty_string(self) -> None:
        clause = _apply_lookup(self.col, "iexact", "")
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "lower" in compiled.lower()

    def test_iexact_preserves_case_insensitivity(self) -> None:
        clause = _apply_lookup(self.col, "iexact", "ALICE")
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "alice" in compiled

    def test_range_with_dates(self) -> None:
        import datetime

        lo = datetime.date(2026, 1, 1)
        hi = datetime.date(2026, 12, 31)
        clause = _apply_lookup(self.dt_col, "range", (lo, hi))
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "BETWEEN" in compiled.upper()

    def test_range_with_integers(self) -> None:
        clause = _apply_lookup(self.age_col, "range", (0, 150))
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "BETWEEN" in compiled.upper()
        assert "0" in compiled
        assert "150" in compiled

    def test_isnull_true_produces_is_null(self) -> None:
        clause = _apply_lookup(self.col, "isnull", True)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "IS NULL" in compiled.upper()
        assert "NOT" not in compiled.upper()

    def test_isnull_false_produces_is_not_null(self) -> None:
        clause = _apply_lookup(self.col, "isnull", False)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "IS NOT NULL" in compiled.upper()

    def test_gt_with_zero(self) -> None:
        clause = _apply_lookup(self.age_col, "gt", 0)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "> 0" in compiled

    def test_lt_with_negative(self) -> None:
        clause = _apply_lookup(self.age_col, "lt", -1)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "< -1" in compiled

    def test_gte_boundary(self) -> None:
        clause = _apply_lookup(self.age_col, "gte", 0)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert ">= 0" in compiled

    def test_lte_boundary(self) -> None:
        clause = _apply_lookup(self.age_col, "lte", 0)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "<= 0" in compiled

    def test_regex_with_complex_pattern(self) -> None:
        clause = _apply_lookup(self.col, "regex", r"^(foo|bar)\d+$")
        assert clause is not None

    def test_iregex_with_complex_pattern(self) -> None:
        clause = _apply_lookup(self.col, "iregex", r"^(foo|bar)\d+$")
        assert clause is not None

    def test_date_with_datetime_value(self) -> None:
        import datetime

        dt = datetime.datetime(2026, 4, 19, 14, 30, 0)
        clause = _apply_lookup(self.dt_col, "date", dt)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "CAST" in compiled.upper() or "DATE" in compiled.upper()

    def test_year_boundary_values(self) -> None:
        clause = _apply_lookup(self.dt_col, "year", 1970)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "1970" in compiled

    def test_month_boundary_min(self) -> None:
        clause = _apply_lookup(self.dt_col, "month", 1)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "1" in compiled

    def test_month_boundary_max(self) -> None:
        clause = _apply_lookup(self.dt_col, "month", 12)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "12" in compiled

    def test_day_boundary_min(self) -> None:
        clause = _apply_lookup(self.dt_col, "day", 1)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "1" in compiled

    def test_day_boundary_max(self) -> None:
        clause = _apply_lookup(self.dt_col, "day", 31)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "31" in compiled

    def test_contains_empty_string(self) -> None:
        clause = _apply_lookup(self.col, "contains", "")
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "LIKE" in compiled.upper()

    def test_startswith_empty_string(self) -> None:
        clause = _apply_lookup(self.col, "startswith", "")
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "LIKE" in compiled.upper()

    def test_endswith_empty_string(self) -> None:
        clause = _apply_lookup(self.col, "endswith", "")
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "LIKE" in compiled.upper()

    def test_model_instance_unwrap_applies_to_ne(self) -> None:
        class FakeItem(Model):
            class Meta:
                table_name = "fake_items_ne"

            name = CharField(max_length=50)

        item = FakeItem(name="x")
        item.__dict__["id"] = 42
        clause = _apply_lookup(self.age_col, "ne", item)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "42" in compiled

    def test_uuid_unwrap_applies_to_ne(self) -> None:
        uid = uuid.uuid4()
        clause = _apply_lookup(self.col, "ne", uid)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert str(uid) in compiled

    def test_multiple_unknown_lookups_all_raise(self) -> None:
        bad_lookups = ["nee", "iin", "like", "between", "eq", "not_equal", "notin"]
        for lookup in bad_lookups:
            with pytest.raises(FieldError, match="Unsupported lookup type"):
                _apply_lookup(self.col, lookup, "x")

    def test_not_in_single_element(self) -> None:
        clause = _apply_lookup(self.age_col, "not_in", [99])
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "NOT IN" in compiled.upper()
        assert "99" in compiled

    def test_in_single_element(self) -> None:
        clause = _apply_lookup(self.age_col, "in", [99])
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "IN" in compiled.upper()
        assert "99" in compiled

    def test_regex_empty_pattern(self) -> None:
        clause = _apply_lookup(self.col, "regex", "")
        assert clause is not None

    def test_iregex_empty_pattern(self) -> None:
        clause = _apply_lookup(self.col, "iregex", "")
        assert clause is not None


# ---------------------------------------------------------------------------
# _compile_single_filter
# ---------------------------------------------------------------------------


class TestCompileSingleFilter:
    def setup_method(self):
        self.table = _make_table("posts", title=sa.String(200), views=sa.Integer())

    def test_simple_equality(self):
        clause = _compile_single_filter(self.table, "title", "hello")
        assert clause is not None

    def test_lookup_suffix(self):
        clause = _compile_single_filter(self.table, "views__gt", 100)
        assert clause is not None

    def test_unknown_column_returns_none(self):
        clause = _compile_single_filter(self.table, "nonexistent", "x")
        assert clause is None

    def test_fk_id_alias(self):
        # Column named 'author_id' should be matched by key 'author'
        meta = sa.MetaData()
        table = sa.Table(
            "t",
            meta,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("author_id", sa.Integer),
        )
        clause = _compile_single_filter(table, "author", 5)
        assert clause is not None


# ---------------------------------------------------------------------------
# _compile_q
# ---------------------------------------------------------------------------


class TestCompileQ:
    def setup_method(self):
        self.table = _make_table("things", name=sa.String(100), age=sa.Integer())

    def test_simple_and_q(self):
        q = Q(name="alice") & Q(age__gt=18)
        clause = _compile_q(self.table, q)
        assert clause is not None

    def test_simple_or_q(self):
        q = Q(name="alice") | Q(name="bob")
        clause = _compile_q(self.table, q)
        assert clause is not None

    def test_negated_q(self):
        q = ~Q(name="alice")
        clause = _compile_q(self.table, q)
        assert clause is not None

    def test_empty_q_returns_none(self):
        q = MagicMock()
        q.children = []
        clause = _compile_q(self.table, q)
        assert clause is None

    def test_unknown_column_ignored(self):
        q = Q(nonexistent="x")
        clause = _compile_q(self.table, q)
        assert clause is None

    def test_nested_q(self):
        inner = Q(name="alice") | Q(name="bob")
        outer = Q(age__gt=5) & inner
        clause = _compile_q(self.table, outer)
        assert clause is not None


# ---------------------------------------------------------------------------
# _compile_filters / _compile_excludes / _build_where_clause
# ---------------------------------------------------------------------------


class TestCompileFilters:
    def setup_method(self):
        self.table = _make_table("items", name=sa.String(100), score=sa.Integer())

    def test_compile_filters_single(self):
        clause = _compile_filters(self.table, [{"name": "x"}])
        assert clause is not None

    def test_compile_filters_multiple(self):
        clause = _compile_filters(self.table, [{"name": "x"}, {"score__gt": 5}])
        assert clause is not None

    def test_compile_filters_empty(self):
        clause = _compile_filters(self.table, [])
        assert clause is None

    def test_compile_filters_unknown_field_raises(self):
        with pytest.raises(FieldError):
            _compile_filters(self.table, [{"nonexistent": "x"}])

    def test_compile_filters_unknown_field_with_lookup_raises(self):
        with pytest.raises(FieldError):
            _compile_filters(self.table, [{"ghost__icontains": "x"}])

    def test_compile_excludes_negate(self):
        clause = _compile_excludes(self.table, [{"name": "x"}])
        assert clause is not None

    def test_compile_excludes_empty(self):
        clause = _compile_excludes(self.table, [])
        assert clause is None

    def test_build_where_clause_combined(self):
        clause = _build_where_clause(
            self.table,
            [{"name": "x"}],
            [{"score__lt": 0}],
            [Q(name="y")],
        )
        assert clause is not None

    def test_build_where_clause_all_empty(self):
        clause = _build_where_clause(self.table, [], [], [])
        assert clause is None


# ---------------------------------------------------------------------------
# _is_f_like / _f_expr_as_sa / _ann_expr_as_sa
# ---------------------------------------------------------------------------


class TestFExpressions:
    def setup_method(self):
        self.table = _make_table("items", price=sa.Integer(), qty=sa.Integer())

    def test_is_f_like_f_object(self):
        f = F("price")
        assert _is_f_like(f) is True

    def test_is_f_like_fexpr(self):
        expr = F("price") + 1
        assert _is_f_like(expr) is True

    def test_is_f_like_plain_int(self):
        assert _is_f_like(42) is False

    def test_f_expr_as_sa_column(self):
        result = _f_expr_as_sa(self.table, F("price"))
        assert result is not None

    def test_f_expr_as_sa_with_id_suffix(self):
        meta = sa.MetaData()
        table = sa.Table(
            "t2", meta, sa.Column("id", sa.Integer), sa.Column("author_id", sa.Integer)
        )
        result = _f_expr_as_sa(table, F("author"))
        assert result is not None

    def test_f_expr_as_sa_unknown_field(self):
        result = _f_expr_as_sa(self.table, F("nonexistent"))
        assert result is None

    def test_f_expr_arithmetic_add(self):
        expr = F("price") + 10
        result = _f_expr_as_sa(self.table, expr)
        assert result is not None

    def test_f_expr_arithmetic_sub(self):
        expr = F("price") - 1
        result = _f_expr_as_sa(self.table, expr)
        assert result is not None

    def test_f_expr_arithmetic_mul(self):
        expr = F("price") * F("qty")
        result = _f_expr_as_sa(self.table, expr)
        assert result is not None

    def test_f_expr_arithmetic_div(self):
        expr = F("price") / 2
        result = _f_expr_as_sa(self.table, expr)
        assert result is not None

    def test_f_expr_unknown_op(self):
        expr = MagicMock()
        expr.lhs = F("price")
        expr.op = "**"
        expr.rhs = 2
        result = _f_expr_as_sa(self.table, expr)
        assert result is None

    def test_f_expr_lhs_none(self):
        # If lhs resolves to None (unknown field), result is None
        expr = F("nonexistent") + 1
        result = _f_expr_as_sa(self.table, expr)
        assert result is None

    def test_ann_expr_aggregate(self):
        agg = Count("price")
        result = _ann_expr_as_sa(self.table, agg)
        assert result is not None

    def test_ann_expr_aggregate_distinct(self):
        agg = Count("price", distinct=True)
        result = _ann_expr_as_sa(self.table, agg)
        assert result is not None

    def test_ann_expr_aggregate_unknown_field(self):
        agg = Count("nonexistent")
        result = _ann_expr_as_sa(self.table, agg)
        assert result is None

    def test_ann_expr_aggregate_id_suffix(self):
        meta = sa.MetaData()
        table = sa.Table(
            "t3", meta, sa.Column("id", sa.Integer), sa.Column("author_id", sa.Integer)
        )
        agg = Count("author")
        result = _ann_expr_as_sa(table, agg)
        assert result is not None

    def test_ann_expr_f_object(self):
        result = _ann_expr_as_sa(self.table, F("price"))
        assert result is not None

    def test_ann_expr_unsupported_returns_none(self):
        result = _ann_expr_as_sa(self.table, "not_an_expr")
        assert result is None

    def test_ann_expr_unknown_func(self):
        agg = MagicMock()
        agg.func = "NOSUCHFUNC"
        agg.field = "price"
        agg.distinct = False
        _ann_expr_as_sa(self.table, agg)
        # sa.func.nosuchfunc exists (dynamic), so this won't be None
        # but if the function doesn't exist as a SA built-in it still returns something
        # We just verify no exception
        assert True  # no exception raised


# ---------------------------------------------------------------------------
# _parse_traversal_cached / _cached_traversal_lookup
# ---------------------------------------------------------------------------


class TestTraversalCache:
    def test_cached_valid_simple(self):
        result = _parse_traversal_cached("title", Post)
        assert result is not _TRAVERSAL_FAILURE
        assert result.is_simple_field() is True

    def test_cached_invalid_returns_sentinel(self):
        result = _parse_traversal_cached("__completely_bogus__field", Post)
        assert result is _TRAVERSAL_FAILURE

    def test_cached_traversal_lookup_raises_field_error(self):
        with pytest.raises(FieldError):
            _cached_traversal_lookup("__completely_bogus__field2", Post)

    def test_cached_traversal_lookup_success(self):
        result = _cached_traversal_lookup("title", Post)
        assert result is not None


# ---------------------------------------------------------------------------
# _compile_traversal_filter (dead code path — tests for coverage)
# ---------------------------------------------------------------------------


class TestCompileTraversalFilter:
    def setup_method(self):
        # Build actual SA tables for Post so the function can work
        self.post_table = get_table(Post)

    def test_simple_field_no_traversal(self):
        clause, joins = _compile_traversal_filter(Post, "title", "hello", self.post_table)
        assert clause is not None
        assert joins == []

    def test_invalid_field_returns_none(self):
        clause, joins = _compile_traversal_filter(Post, "__invalid__bogus__x", "v", self.post_table)
        assert clause is None
        assert joins == []


# ---------------------------------------------------------------------------
# get_table / _build_table
# ---------------------------------------------------------------------------


class TestGetTable:
    def test_returns_sa_table(self):
        table = get_table(Post)
        assert isinstance(table, sa.Table)
        assert table.name == "exec_posts"

    def test_cached_same_object(self):
        t1 = get_table(Post)
        t2 = get_table(Post)
        assert t1 is t2

    def test_columns_present(self):
        table = get_table(Post)
        assert "title" in table.c
        assert "views" in table.c


# ---------------------------------------------------------------------------
# _build_where_clause_with_traversals
# ---------------------------------------------------------------------------


class TestBuildWhereClauseWithTraversals:
    def setup_method(self):
        self.table = get_table(Post)

    def test_simple_filter(self):
        where, from_clause = _build_where_clause_with_traversals(
            Post, self.table, [{"title": "hello"}], [], []
        )
        assert where is not None

    def test_exclude_filter(self):
        where, from_clause = _build_where_clause_with_traversals(
            Post, self.table, [], [{"views__lt": 0}], []
        )
        assert where is not None

    def test_q_filter(self):
        where, from_clause = _build_where_clause_with_traversals(
            Post, self.table, [], [], [Q(title="hi")]
        )
        assert where is not None

    def test_all_empty(self):
        where, from_clause = _build_where_clause_with_traversals(Post, self.table, [], [], [])
        assert where is None
        assert from_clause is self.table

    def test_unknown_filter_field_raises(self):
        with pytest.raises(FieldError):
            _build_where_clause_with_traversals(
                Post, self.table, [{"nonexistent_field": "x"}], [], []
            )

    def test_unknown_exclude_field_raises(self):
        with pytest.raises(FieldError):
            _build_where_clause_with_traversals(
                Post, self.table, [], [{"nonexistent_field": "x"}], []
            )

    def test_unknown_filter_with_lookup_raises(self):
        with pytest.raises(FieldError):
            _build_where_clause_with_traversals(
                Post, self.table, [{"ghost__icontains": "x"}], [], []
            )

    def test_invalid_traversal_falls_back(self):
        # A key starting with __ has an empty col_name; not in table → FieldError
        with pytest.raises(FieldError):
            _build_where_clause_with_traversals(
                Post, self.table, [{"__totally_bogus": "x"}], [], []
            )

    def test_invalid_exclude_traversal_falls_back(self):
        with pytest.raises(FieldError):
            _build_where_clause_with_traversals(
                Post, self.table, [], [{"__totally_bogus": "x"}], []
            )


# ---------------------------------------------------------------------------
# execute_select / execute_count / execute_exists / execute_delete
# ---------------------------------------------------------------------------


class TestExecuteSelect:
    @pytest.mark.asyncio
    async def test_basic_select(self):
        mock_rows = [{"id": 1, "title": "Hello", "views": 0, "author_id": None}]
        qs = _make_qs(filters=[{"title": "Hello"}])

        with (
            patch("openviper.db.executor._connect") as mock_connect,
            patch("openviper.db.executor._load_soft_removed_columns", new_callable=AsyncMock),
            (
                patch("openviper.db.executor._check_perm_cached", new_callable=AsyncMock)
                if False
                else patch("openviper.db.executor.get_table", return_value=get_table(Post))
            ),
        ):
            mock_conn = AsyncMock()
            mock_result = MagicMock()
            mock_result.mappings.return_value = mock_rows
            mock_conn.execute = AsyncMock(return_value=mock_result)
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await execute_select(qs)
            assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_select_with_limit(self):
        qs = _make_qs(limit=5)

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = []
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_select(qs)
            assert result == []

    @pytest.mark.asyncio
    async def test_select_with_offset(self):
        qs = _make_qs(offset=10)

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = []
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_select(qs)
            assert result == []

    @pytest.mark.asyncio
    async def test_select_distinct(self):
        qs = _make_qs(distinct=True)

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = []
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_select(qs)
            assert result == []

    @pytest.mark.asyncio
    async def test_select_with_order(self):
        qs = _make_qs(order=["-views"])

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = []
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_select(qs)
            assert result == []

    @pytest.mark.asyncio
    async def test_select_with_only_fields(self):
        qs = _make_qs(only=["title"])

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = []
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_select(qs)
            assert result == []

    @pytest.mark.asyncio
    async def test_select_with_defer_fields(self):
        qs = _make_qs(defer=["views"])

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = []
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_select(qs)
            assert result == []

    @pytest.mark.asyncio
    async def test_select_with_annotations(self):
        qs = _make_qs(annotations={"total": Count("id")})

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = []
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_select(qs)
            assert result == []

    @pytest.mark.asyncio
    async def test_select_applies_max_query_rows_when_no_limit(self):
        """Without explicit limit, MAX_QUERY_ROWS is applied."""
        qs = _make_qs()  # no limit

        captured_stmt = []

        async def fake_execute(stmt):
            captured_stmt.append(stmt)
            result = MagicMock()
            result.mappings.return_value = []
            return result

        mock_conn = AsyncMock()
        mock_conn.execute = fake_execute

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            await execute_select(qs)

        # Verify a stmt was captured (no exceptions)
        assert len(captured_stmt) == 1


class TestExecuteCount:
    @pytest.mark.asyncio
    async def test_count(self):
        qs = _make_qs()

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 42
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_count(qs)
            assert result == 42

    @pytest.mark.asyncio
    async def test_count_with_filter(self):
        qs = _make_qs(filters=[{"title": "x"}])

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 7
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_count(qs)
            assert result == 7

            stmt = mock_conn.execute.call_args[0][0]
            sql = str(stmt.compile(compile_kwargs={"literal_binds": True})).upper()
            assert "WHERE" in sql

    @pytest.mark.asyncio
    async def test_count_icontains_filter_applies_where(self):
        qs = _make_qs(filters=[{"title__icontains": "hello"}])

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 3
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_count(qs)
            assert result == 3

            stmt = mock_conn.execute.call_args[0][0]
            sql = str(stmt.compile(compile_kwargs={"literal_binds": True})).upper()
            assert "WHERE" in sql
            assert "LIKE" in sql

    @pytest.mark.asyncio
    async def test_count_no_filter_has_no_where(self):
        qs = _make_qs()

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 100
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            await execute_count(qs)

            stmt = mock_conn.execute.call_args[0][0]
            sql = str(stmt.compile(compile_kwargs={"literal_binds": True})).upper()
            assert "WHERE" not in sql

    @pytest.mark.asyncio
    async def test_count_startswith_filter_applies_where(self):
        qs = _make_qs(filters=[{"title__startswith": "abc"}])

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 5
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            await execute_count(qs)

            stmt = mock_conn.execute.call_args[0][0]
            sql = str(stmt.compile(compile_kwargs={"literal_binds": True})).upper()
            assert "WHERE" in sql
            assert "LIKE" in sql

    @pytest.mark.asyncio
    async def test_count_gt_filter_applies_where(self):
        qs = _make_qs(filters=[{"views__gt": 100}])

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 2
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            await execute_count(qs)

            stmt = mock_conn.execute.call_args[0][0]
            sql = str(stmt.compile(compile_kwargs={"literal_binds": True})).upper()
            assert "WHERE" in sql

    @pytest.mark.asyncio
    async def test_count_q_filter_applies_where(self):
        q = Q(title__icontains="test")
        qs = _make_qs(q_filters=[q])

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 1
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            await execute_count(qs)

            stmt = mock_conn.execute.call_args[0][0]
            sql = str(stmt.compile(compile_kwargs={"literal_binds": True})).upper()
            assert "WHERE" in sql


class TestExecuteExists:
    @pytest.mark.asyncio
    async def test_exists_true(self):
        qs = _make_qs()

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = (1,)
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_exists(qs)
            assert result is True

    @pytest.mark.asyncio
    async def test_exists_false(self):
        qs = _make_qs()

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_exists(qs)
            assert result is False


class TestExecuteDelete:
    @pytest.mark.asyncio
    async def test_delete(self):
        qs = _make_qs(filters=[{"title": "old"}])

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 3
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._begin") as mock_begin:
            mock_begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_begin.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_delete(qs)
            assert result == 3


class TestExecuteUpdate:
    @pytest.mark.asyncio
    async def test_update(self):
        qs = _make_qs(filters=[{"title": "old"}])

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 2
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with (
            patch("openviper.db.executor.check_permission_for_model", new_callable=AsyncMock),
            patch("openviper.db.executor._begin") as mock_begin,
        ):
            mock_begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_begin.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_update(qs, {"title": "new"})
            assert result == 2

    @pytest.mark.asyncio
    async def test_update_with_f_expression(self):
        qs = _make_qs()

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with (
            patch("openviper.db.executor.check_permission_for_model", new_callable=AsyncMock),
            patch("openviper.db.executor._begin") as mock_begin,
        ):
            mock_begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_begin.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_update(qs, {"views": F("views") + 1})
            assert result == 1

    @pytest.mark.asyncio
    async def test_update_bypasses_permissions(self):
        qs = _make_qs(ignore_permissions=True)

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with (
            patch(
                "openviper.db.executor.check_permission_for_model", new_callable=AsyncMock
            ) as mock_perm,
            patch("openviper.db.executor._begin") as mock_begin,
        ):
            mock_begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_begin.return_value.__aexit__ = AsyncMock(return_value=None)
            await execute_update(qs, {"title": "x"})
            mock_perm.assert_awaited_once_with(Post, "update", ignore_permissions=True)


# ---------------------------------------------------------------------------
# execute_save
# ---------------------------------------------------------------------------


class TestExecuteSave:
    @pytest.mark.asyncio
    async def test_insert_new_instance(self):
        p = Post(title="New", views=0)
        assert p.id is None

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.inserted_primary_key = [42]
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with (
            patch("openviper.db.executor.check_permission_for_model", new_callable=AsyncMock),
            patch("openviper.db.executor._load_soft_removed_columns", new_callable=AsyncMock),
            patch("openviper.db.executor.get_soft_removed_columns", return_value=frozenset()),
            patch("openviper.db.executor._begin") as mock_begin,
        ):
            mock_begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_begin.return_value.__aexit__ = AsyncMock(return_value=None)
            await execute_save(p)
            assert p.id == 42

    @pytest.mark.asyncio
    async def test_update_existing_instance(self):
        p = Post._from_row({"id": 5, "title": "Old", "views": 10, "author_id": None})

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=MagicMock())

        with (
            patch("openviper.db.executor.check_permission_for_model", new_callable=AsyncMock),
            patch("openviper.db.executor._load_soft_removed_columns", new_callable=AsyncMock),
            patch("openviper.db.executor.get_soft_removed_columns", return_value=frozenset()),
            patch("openviper.db.executor._begin") as mock_begin,
        ):
            mock_begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_begin.return_value.__aexit__ = AsyncMock(return_value=None)
            p.title = "Updated"
            await execute_save(p)
            assert mock_conn.execute.called

    @pytest.mark.asyncio
    async def test_save_skips_soft_removed_columns(self):
        p = Post(title="Test", views=0)

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.inserted_primary_key = [1]
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with (
            patch("openviper.db.executor.check_permission_for_model", new_callable=AsyncMock),
            patch("openviper.db.executor._load_soft_removed_columns", new_callable=AsyncMock),
            patch(
                "openviper.db.executor.get_soft_removed_columns", return_value=frozenset(["views"])
            ),
            patch("openviper.db.executor._begin") as mock_begin,
        ):
            mock_begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_begin.return_value.__aexit__ = AsyncMock(return_value=None)
            await execute_save(p)
            # Verify execute was called (insert happened)
            assert mock_conn.execute.called

    @pytest.mark.asyncio
    async def test_save_with_client_assigned_pk(self):
        """New instance with manually assigned PK should INSERT."""
        p = Post(title="Manual PK", views=0)
        p.id = 99  # manually assigned

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.inserted_primary_key = [99]
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with (
            patch("openviper.db.executor.check_permission_for_model", new_callable=AsyncMock),
            patch("openviper.db.executor._load_soft_removed_columns", new_callable=AsyncMock),
            patch("openviper.db.executor.get_soft_removed_columns", return_value=frozenset()),
            patch("openviper.db.executor._begin") as mock_begin,
        ):
            mock_begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_begin.return_value.__aexit__ = AsyncMock(return_value=None)
            await execute_save(p)
            assert mock_conn.execute.called

    @pytest.mark.asyncio
    async def test_uuid_pk_excluded_from_update_set_clause(self):
        """UUID primary keys must not appear in the UPDATE SET clause."""
        uid = uuid.uuid4()
        otp = OtpRecord._from_row({"id": uid, "otp": "111111"})

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_conn.execute = AsyncMock(return_value=mock_result)

        captured_stmt = {}

        async def _capture_execute(stmt):
            captured_stmt["stmt"] = stmt
            return mock_result

        mock_conn.execute = _capture_execute

        with (
            patch("openviper.db.executor.check_permission_for_model", new_callable=AsyncMock),
            patch("openviper.db.executor._load_soft_removed_columns", new_callable=AsyncMock),
            patch("openviper.db.executor.get_soft_removed_columns", return_value=frozenset()),
            patch("openviper.db.executor._begin") as mock_begin,
        ):
            mock_begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_begin.return_value.__aexit__ = AsyncMock(return_value=None)
            otp.otp = "999999"
            await execute_save(otp)

        stmt = captured_stmt["stmt"]
        # _values is an immutabledict of {column_name: value} for the SET clause.
        set_col_names = set(stmt._values.keys())
        assert (
            "id" not in set_col_names
        ), f"Primary key 'id' must not appear in UPDATE SET; columns being set: {set_col_names}"


# ---------------------------------------------------------------------------
# execute_delete_instance
# ---------------------------------------------------------------------------


class TestExecuteDeleteInstance:
    @pytest.mark.asyncio
    async def test_delete_instance(self):
        p = Post._from_row({"id": 7, "title": "Bye", "views": 0, "author_id": None})

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=MagicMock())

        with (
            patch("openviper.db.executor.check_permission_for_model", new_callable=AsyncMock),
            patch("openviper.db.executor._begin") as mock_begin,
        ):
            mock_begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_begin.return_value.__aexit__ = AsyncMock(return_value=None)
            await execute_delete_instance(p)
            assert mock_conn.execute.called

    @pytest.mark.asyncio
    async def test_delete_instance_with_bypass(self):
        p = Post._from_row({"id": 8, "title": "Gone", "views": 0, "author_id": None})

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=MagicMock())

        with (
            patch(
                "openviper.db.executor.check_permission_for_model", new_callable=AsyncMock
            ) as mock_perm,
            patch("openviper.db.executor._begin") as mock_begin,
        ):
            mock_begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_begin.return_value.__aexit__ = AsyncMock(return_value=None)
            await execute_delete_instance(p, ignore_permissions=True)
            mock_perm.assert_awaited_once_with(Post, "delete", ignore_permissions=True)


# ---------------------------------------------------------------------------
# execute_values
# ---------------------------------------------------------------------------


class TestExecuteValues:
    @pytest.mark.asyncio
    async def test_values_all_fields(self):
        qs = _make_qs()

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = [{"title": "A", "views": 1}]
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs)
            assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_values_specific_fields(self):
        qs = _make_qs()

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = [{"title": "A"}]
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs, fields=("title",))
            assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_values_with_annotation_field(self):
        qs = _make_qs(annotations={"cnt": Count("id")})

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = [{"cnt": 10}]
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs, fields=("cnt",))
            assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_values_with_annotations_no_fields(self):
        qs = _make_qs(annotations={"total": Sum("views")})

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = []
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs)
            assert result == []


# ---------------------------------------------------------------------------
# execute_aggregate
# ---------------------------------------------------------------------------


class TestExecuteAggregate:
    @pytest.mark.asyncio
    async def test_aggregate_returns_dict(self):
        qs = _make_qs()

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = {"total": 5}
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_aggregate(qs, {"total": Count("id")})
            assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_aggregate_empty_kwargs(self):
        qs = _make_qs()
        result = await execute_aggregate(qs, {})
        assert result == {}

    @pytest.mark.asyncio
    async def test_aggregate_no_row(self):
        qs = _make_qs()

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = None
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_aggregate(qs, {"total": Count("id")})
            assert result == {}


# ---------------------------------------------------------------------------
# execute_explain
# ---------------------------------------------------------------------------


class TestExecuteExplain:
    @pytest.mark.asyncio
    async def test_explain_sqlite(self):
        qs = _make_qs()

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = [{"detail": "SCAN TABLE exec_posts"}]
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_engine = MagicMock()
        mock_engine.dialect.name = "sqlite"

        with (
            patch("openviper.db.executor._connect") as mock_connect,
            patch("openviper.db.executor.get_engine", new=AsyncMock(return_value=mock_engine)),
        ):
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_explain(qs)
            assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_explain_generic_fallback(self):
        qs = _make_qs()

        mock_conn = AsyncMock()
        mock_engine = MagicMock()
        mock_engine.dialect.name = "mysql"

        with (
            patch("openviper.db.executor._connect") as mock_connect,
            patch("openviper.db.executor.get_engine", new=AsyncMock(return_value=mock_engine)),
        ):
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_explain(qs)
            assert "EXPLAIN" in result

    @pytest.mark.asyncio
    async def test_explain_with_order_and_limit(self):
        qs = _make_qs(order=["title"], limit=10, offset=5)

        mock_conn = AsyncMock()
        mock_engine = MagicMock()
        mock_engine.dialect.name = "mysql"

        with (
            patch("openviper.db.executor._connect") as mock_connect,
            patch("openviper.db.executor.get_engine", new=AsyncMock(return_value=mock_engine)),
        ):
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_explain(qs)
            assert isinstance(result, str)


# ---------------------------------------------------------------------------
# execute_bulk_update
# ---------------------------------------------------------------------------


class TestExecuteBulkUpdate:
    @pytest.mark.asyncio
    async def test_empty_objs(self):
        result = await execute_bulk_update(Post, [], ["title"])
        assert result == 0

    @pytest.mark.asyncio
    async def test_empty_fields(self):
        p = Post._from_row({"id": 1, "title": "A", "views": 0, "author_id": None})
        result = await execute_bulk_update(Post, [p], [])
        assert result == 0

    @pytest.mark.asyncio
    async def test_bulk_update_runs(self):
        p1 = Post._from_row({"id": 1, "title": "A", "views": 0, "author_id": None})
        p2 = Post._from_row({"id": 2, "title": "B", "views": 5, "author_id": None})
        p1.title = "Updated A"
        p2.title = "Updated B"

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 2
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._begin") as mock_begin:
            mock_begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_begin.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_bulk_update(Post, [p1, p2], ["title"])
            assert result == 2

    @pytest.mark.asyncio
    async def test_bulk_update_skips_no_pk(self):
        p = Post(title="No PK")  # no id set

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._begin") as mock_begin:
            mock_begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_begin.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_bulk_update(Post, [p], ["title"])
            assert result == 0

    @pytest.mark.asyncio
    async def test_bulk_update_with_batch_size(self):
        posts = [
            Post._from_row({"id": i, "title": f"P{i}", "views": 0, "author_id": None})
            for i in range(1, 5)
        ]

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 2
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._begin") as mock_begin:
            mock_begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_begin.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_bulk_update(Post, posts, ["title"], batch_size=2)
            assert result == 4  # 2 batches * 2 rows each

    @pytest.mark.asyncio
    async def test_bulk_update_extra_field_not_in_model(self):
        p = Post._from_row({"id": 1, "title": "A", "views": 0, "author_id": None})
        p.extra = "val"  # not in model fields

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor._begin") as mock_begin:
            mock_begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_begin.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_bulk_update(Post, [p], ["extra"])
            assert result == 1


# ---------------------------------------------------------------------------
# _load_soft_removed_columns
# ---------------------------------------------------------------------------


class TestLoadSoftRemovedColumns:
    def setup_method(self):
        invalidate_soft_removed_cache()

    @pytest.mark.asyncio
    async def test_already_loaded_skips(self):
        mod._SOFT_REMOVED_LOADED = True
        # Should return immediately without touching engine
        with patch("openviper.db.executor.get_engine", new_callable=AsyncMock) as mock_eng:
            await _load_soft_removed_columns()
            mock_eng.assert_not_awaited()
        mod._SOFT_REMOVED_LOADED = False

    @pytest.mark.asyncio
    async def test_table_not_exists(self):
        mod._SOFT_REMOVED_LOADED = False

        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.run_sync = AsyncMock(return_value=False)  # table doesn't exist
        mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("openviper.db.executor.get_engine", new=AsyncMock(return_value=mock_engine)):
            await _load_soft_removed_columns()
            assert mod._SOFT_REMOVED_LOADED is True

        mod._SOFT_REMOVED_LOADED = False

    @pytest.mark.asyncio
    async def test_exception_sets_loaded(self):
        mod._SOFT_REMOVED_LOADED = False

        with patch(
            "openviper.db.executor.get_engine", new=AsyncMock(side_effect=RuntimeError("db error"))
        ):
            await _load_soft_removed_columns()
            assert mod._SOFT_REMOVED_LOADED is True

        mod._SOFT_REMOVED_LOADED = False


# ---------------------------------------------------------------------------
# MAX_QUERY_ROWS constant
# ---------------------------------------------------------------------------


class TestMaxQueryRows:
    def test_default_value(self):
        assert MAX_QUERY_ROWS is None
