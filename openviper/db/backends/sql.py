"""Default SQL backend for virtual models."""

from __future__ import annotations

import builtins
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

import sqlalchemy as sa

from openviper.db.backends.base import VirtualBackend, VirtualBackendCapabilities
from openviper.db.executor import begin, connect, escape_like, get_table
from openviper.db.fields import ForeignKey, ManyToManyField
from openviper.db.queryspec import FilterClause, FilterOp, QuerySpec

if TYPE_CHECKING:
    from openviper.db.models import Model


class SQLVirtualBackend(VirtualBackend):
    """Read and write virtual models through the configured SQL connection."""

    capabilities = VirtualBackendCapabilities(
        supports_count=True,
        supports_filter_ops=True,
        supports_distinct=True,
        supports_only=True,
        supports_defer=True,
        supports_bulk_create=True,
        supports_bulk_update=True,
        supports_bulk_delete=True,
    )

    async def get(
        self,
        model_class: type[Model],
        primary_key: object,
    ) -> Mapping[str, object] | None:
        query = QuerySpec(filters={"id": primary_key}, limit=1)
        rows = await self.list(model_class, query)
        return rows[0] if rows else None

    async def list(
        self,
        model_class: type[Model],
        query: QuerySpec,
    ) -> Sequence[Mapping[str, object]]:
        table = get_table(model_class)
        stmt = sa.select(table)
        where_clause = self.build_where_clause(table, query.filters)
        if where_clause is not None:
            stmt = stmt.where(where_clause)
        filter_clause_expr = self.build_filter_clause_where(table, query.filter_clauses)
        if filter_clause_expr is not None:
            stmt = stmt.where(filter_clause_expr)
        for field_name in query.order_by or ():
            column = self.resolve_order_column(table, field_name)
            stmt = stmt.order_by(column)
        if query.limit is not None:
            stmt = stmt.limit(query.limit)
        if query.offset is not None:
            stmt = stmt.offset(query.offset)
        if query.distinct:
            stmt = stmt.distinct()
        if query.only_fields:
            cols = [table.c[f] for f in query.only_fields if f in table.c]
            if cols:
                stmt = stmt.with_only_columns(*cols)
        elif query.defer_fields:
            all_cols = set(table.c.keys())
            defer_set = set(query.defer_fields)
            cols = [table.c[f] for f in all_cols - defer_set if f in table.c]
            if cols:
                stmt = stmt.with_only_columns(*cols)
        async with connect(model_class=model_class) as conn:
            result = await conn.execute(stmt)
            return [dict(row) for row in result.mappings().all()]

    async def create(
        self,
        model_class: type[Model],
        data: Mapping[str, object],
    ) -> Mapping[str, object]:
        table = get_table(model_class)
        values = self.to_column_values(model_class, data, include_primary_key=False)
        stmt = sa.insert(table).values(**values)
        async with begin(model_class=model_class) as conn:
            result = await conn.execute(stmt)
        if "id" not in values and result.inserted_primary_key:
            values["id"] = result.inserted_primary_key[0]
        return values

    async def bulk_create(
        self,
        model_class: type[Model],
        data_list: Sequence[Mapping[str, object]],
    ) -> Sequence[Mapping[str, object]]:
        """Create multiple records in a single transaction."""
        if not data_list:
            return []
        table = get_table(model_class)
        rows = [
            self.to_column_values(model_class, data, include_primary_key=False)
            for data in data_list
        ]
        async with begin(model_class=model_class) as conn:
            stmt = sa.insert(table)
            if getattr(conn.engine.dialect, "insert_executemany_returning", False):
                result = await conn.execute(stmt.returning(*table.c), rows)
                return [dict(row) for row in result.mappings().all()]
            result = await conn.execute(stmt, rows)
        primary_key_rows = getattr(result, "inserted_primary_key_rows", None)
        if primary_key_rows:
            self.apply_inserted_primary_keys(table, rows, primary_key_rows)
        return rows

    async def update(
        self,
        model_class: type[Model],
        primary_key: object,
        data: Mapping[str, object],
    ) -> Mapping[str, object]:
        table = get_table(model_class)
        values = self.to_column_values(model_class, data, include_primary_key=False)
        stmt = sa.update(table).where(table.c.id == primary_key).values(**values)
        async with begin(model_class=model_class) as conn:
            await conn.execute(stmt)
        row = await self.get(model_class, primary_key)
        return row or {"id": primary_key, **values}

    async def bulk_update(
        self,
        model_class: type[Model],
        updates: Sequence[tuple[object, Mapping[str, object]]],
    ) -> int:
        """Update multiple records in a single transaction."""
        if not updates:
            return 0
        table = get_table(model_class)
        batches: dict[tuple[str, ...], list[dict[str, object]]] = {}
        for pk, data in updates:
            values = self.to_column_values(model_class, data, include_primary_key=False)
            if not values:
                continue
            columns = tuple(sorted(values))
            params = {"_pk": pk}
            params.update({f"value_{column}": value for column, value in values.items()})
            batches.setdefault(columns, []).append(params)

        updated = 0
        async with begin(model_class=model_class) as conn:
            for columns, batch in batches.items():
                stmt = (
                    sa.update(table)
                    .where(table.c.id == sa.bindparam("_pk"))
                    .values({column: sa.bindparam(f"value_{column}") for column in columns})
                )
                result = await conn.execute(stmt, batch)
                rowcount = result.rowcount
                updated += rowcount if rowcount is not None and rowcount >= 0 else len(batch)
        return updated

    async def delete(
        self,
        model_class: type[Model],
        primary_key: object,
    ) -> None:
        table = get_table(model_class)
        stmt = sa.delete(table).where(table.c.id == primary_key)
        async with begin(model_class=model_class) as conn:
            await conn.execute(stmt)

    async def bulk_delete(
        self,
        model_class: type[Model],
        primary_keys: Sequence[object],
    ) -> int:
        """Delete multiple records in a single transaction."""
        table = get_table(model_class)
        async with begin(model_class=model_class) as conn:
            stmt = sa.delete(table).where(table.c.id.in_(list(primary_keys)))
            result = await conn.execute(stmt)
            return int(result.rowcount or 0)

    async def count(
        self,
        model_class: type[Model],
        query: QuerySpec,
    ) -> int:
        """Return the number of rows matching *query* using SQL COUNT."""
        table = get_table(model_class)
        base_stmt = sa.select(table)
        where_clause = self.build_where_clause(table, query.filters)
        if where_clause is not None:
            base_stmt = base_stmt.where(where_clause)
        filter_clause_expr = self.build_filter_clause_where(table, query.filter_clauses)
        if filter_clause_expr is not None:
            base_stmt = base_stmt.where(filter_clause_expr)
        if query.distinct:
            stmt = sa.select(sa.func.count()).select_from(base_stmt.distinct().subquery())
        else:
            stmt = sa.select(sa.func.count()).select_from(base_stmt.subquery())
        async with connect(model_class=model_class) as conn:
            result = await conn.execute(stmt)
            return int(result.scalar() or 0)

    def build_where_clause(
        self,
        table: sa.Table,
        filters: Mapping[str, object],
    ) -> sa.ColumnElement[bool] | None:
        clauses: list[sa.ColumnElement[bool]] = []
        for field_name, value in filters.items():
            column_name = "id" if field_name == "pk" else field_name
            if column_name not in table.c:
                raise ValueError(f"Unknown virtual SQL field '{field_name}'.")
            clauses.append(table.c[column_name] == value)
        return sa.and_(*clauses) if clauses else None

    def build_filter_clause_where(
        self,
        table: sa.Table,
        filter_clauses: Sequence[FilterClause],
    ) -> sa.ColumnElement[bool] | None:
        """Translate structured FilterClause predicates into SQLAlchemy WHERE expressions."""
        if not filter_clauses:
            return None
        clauses: list[sa.ColumnElement[bool]] = []
        for fc in filter_clauses:
            if fc.field not in table.c:
                raise ValueError(f"Unknown virtual SQL field '{fc.field}'.")
            col = table.c[fc.field]
            if fc.op == FilterOp.EQ:
                clauses.append(col == fc.value)
            elif fc.op == FilterOp.NE:
                clauses.append(col != fc.value)
            elif fc.op == FilterOp.GT:
                clauses.append(col > fc.value)
            elif fc.op == FilterOp.GTE:
                clauses.append(col >= fc.value)
            elif fc.op == FilterOp.LT:
                clauses.append(col < fc.value)
            elif fc.op == FilterOp.LTE:
                clauses.append(col <= fc.value)
            elif fc.op == FilterOp.IN:
                clauses.append(col.in_(self.filter_sequence(fc)))
            elif fc.op == FilterOp.NOT_IN:
                clauses.append(col.notin_(self.filter_sequence(fc)))
            elif fc.op == FilterOp.CONTAINS:
                clauses.append(col.contains(escape_like(str(fc.value)), escape="\\"))
            elif fc.op == FilterOp.ICONTAINS:
                clauses.append(col.ilike(f"%{escape_like(str(fc.value))}%", escape="\\"))
            elif fc.op == FilterOp.STARTSWITH:
                clauses.append(col.startswith(escape_like(str(fc.value)), escape="\\"))
            elif fc.op == FilterOp.ENDSWITH:
                clauses.append(col.endswith(escape_like(str(fc.value)), escape="\\"))
            elif fc.op == FilterOp.IS_NULL:
                clauses.append(col.is_(None) if fc.value else col.isnot(None))
            else:
                raise ValueError(f"Unsupported filter operation: {fc.op}")
        return sa.and_(*clauses) if clauses else None

    def filter_sequence(self, clause: FilterClause) -> Sequence[object]:
        """Return the iterable operand for an IN predicate."""
        if isinstance(clause.value, Sequence) and not isinstance(
            clause.value,
            (str, bytes, bytearray),
        ):
            return clause.value
        raise ValueError(f"Filter operation {clause.op.value} requires a sequence.")

    def apply_inserted_primary_keys(
        self,
        table: sa.Table,
        rows: builtins.list[dict[str, object]],
        primary_key_rows: Sequence[Sequence[object]],
    ) -> None:
        """Populate auto primary keys returned by batched inserts."""
        primary_keys = tuple(table.primary_key.columns)
        if len(primary_keys) != 1:
            return
        primary_key_name = primary_keys[0].name
        for row, primary_key_row in zip(rows, primary_key_rows, strict=False):
            if primary_key_name not in row and primary_key_row:
                row[primary_key_name] = primary_key_row[0]

    def resolve_order_column(
        self,
        table: sa.Table,
        field_name: str,
    ) -> sa.ColumnElement[object]:
        descending = field_name.startswith("-")
        column_name = field_name[1:] if descending else field_name
        if column_name not in table.c:
            raise ValueError(f"Unknown virtual SQL order field '{field_name}'.")
        column = table.c[column_name]
        return column.desc() if descending else column.asc()

    def to_column_values(
        self,
        model_class: type[Model],
        data: Mapping[str, object],
        *,
        include_primary_key: bool,
    ) -> dict[str, object]:
        values: dict[str, object] = {}
        for field_name, field in model_class._fields.items():
            if isinstance(field, ManyToManyField):
                continue
            if field.primary_key and field.auto_increment and not include_primary_key:
                continue
            if field_name not in data and field.column_name not in data:
                continue
            value = data[field_name] if field_name in data else data[field.column_name]
            column_name = field.column_name
            if isinstance(field, ForeignKey):
                values[column_name] = value
            else:
                values[column_name] = field.to_db(value)
        return values
