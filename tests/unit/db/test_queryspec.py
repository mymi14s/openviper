"""Tests for the QuerySpec, FilterOp, and FilterClause data structures."""

from __future__ import annotations

import pytest

from openviper.db.queryspec import FilterClause, FilterOp, QuerySpec

# ── FilterOp ──────────────────────────────────────────────────────────────────


class TestFilterOp:
    def test_filter_op_values(self) -> None:
        assert FilterOp.EQ.value == "eq"
        assert FilterOp.NE.value == "ne"
        assert FilterOp.GT.value == "gt"
        assert FilterOp.GTE.value == "gte"
        assert FilterOp.LT.value == "lt"
        assert FilterOp.LTE.value == "lte"
        assert FilterOp.IN.value == "in"
        assert FilterOp.NOT_IN.value == "not_in"
        assert FilterOp.CONTAINS.value == "contains"
        assert FilterOp.ICONTAINS.value == "icontains"
        assert FilterOp.STARTSWITH.value == "startswith"
        assert FilterOp.ENDSWITH.value == "endswith"
        assert FilterOp.IS_NULL.value == "is_null"

    def test_filter_op_from_string(self) -> None:
        assert FilterOp("eq") == FilterOp.EQ
        assert FilterOp("gt") == FilterOp.GT


# ── FilterClause ──────────────────────────────────────────────────────────────


class TestFilterClause:
    def test_filter_clause_creation(self) -> None:
        clause = FilterClause(field="name", op=FilterOp.EQ, value="test")
        assert clause.field == "name"
        assert clause.op == FilterOp.EQ
        assert clause.value == "test"

    def test_filter_clause_equality(self) -> None:
        clause1 = FilterClause(field="name", op=FilterOp.EQ, value="test")
        clause2 = FilterClause(field="name", op=FilterOp.EQ, value="test")
        assert clause1 == clause2

    def test_filter_clause_inequality_different_op(self) -> None:
        clause1 = FilterClause(field="name", op=FilterOp.EQ, value="test")
        clause2 = FilterClause(field="name", op=FilterOp.NE, value="test")
        assert clause1 != clause2


# ── QuerySpec ─────────────────────────────────────────────────────────────────


class TestQuerySpec:
    def test_default_queryspec(self) -> None:
        spec = QuerySpec()
        assert spec.filters == {}
        assert spec.filter_clauses == ()
        assert spec.order_by is None
        assert spec.limit is None
        assert spec.offset is None
        assert spec.only_fields == ()
        assert spec.defer_fields == ()
        assert spec.distinct is False

    def test_queryspec_with_filters(self) -> None:
        clause = FilterClause(field="status", op=FilterOp.EQ, value="active")
        spec = QuerySpec(filter_clauses=(clause,))
        assert len(spec.filter_clauses) == 1
        assert spec.filter_clauses[0].field == "status"

    def test_queryspec_with_ordering(self) -> None:
        spec = QuerySpec(order_by=("-created_at", "name"))
        assert spec.order_by == ("-created_at", "name")

    def test_queryspec_with_limit_offset(self) -> None:
        spec = QuerySpec(limit=10, offset=20)
        assert spec.limit == 10
        assert spec.offset == 20

    def test_queryspec_with_only_fields(self) -> None:
        spec = QuerySpec(only_fields=("id", "name"))
        assert spec.only_fields == ("id", "name")

    def test_queryspec_with_distinct(self) -> None:
        spec = QuerySpec(distinct=True)
        assert spec.distinct is True

    def test_queryspec_with_dict_filters(self) -> None:
        spec = QuerySpec(filters={"status": "active", "age": 25})
        assert spec.filters == {"status": "active", "age": 25}

    def test_queryspec_equality(self) -> None:
        spec1 = QuerySpec(limit=10, offset=0)
        spec2 = QuerySpec(limit=10, offset=0)
        assert spec1 == spec2
