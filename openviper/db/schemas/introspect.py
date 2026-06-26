"""
Introspect live database schema using SQLAlchemy inspect().
Produces state dicts in the same format as ``model_state_snapshot``
so that ``diff_states`` can compare desired JSON state against actual
database state.
"""

from __future__ import annotations

import logging
import typing as t

import sqlalchemy as sa

from openviper.db.connection import get_engine
from openviper.db.connections import connections
from openviper.db.dialects import resolve_dialect_by_vendor

logger = logging.getLogger("openviper.schemas")


async def get_async_engine(db_alias: str = "default") -> t.Any:
    """Return the async engine for the given database alias."""
    if db_alias == "default":
        try:
            if connections.initialized and "default" in connections.backends:
                return await connections.get("default").create_engine()
        except Exception:
            logger.debug("Falling back to default engine for schema introspection")
    return await get_engine()


def introspect_table_sync(
    sync_conn: sa.Connection,
    table_name: str,
) -> dict[str, t.Any] | None:
    """Synchronously introspect a single table's schema.

    Args:
        sync_conn: SQLAlchemy sync connection (from run_sync).
        table_name: Name of the table to introspect.

    Returns:
        State dict for the table, or None if the table does not exist.
    """
    inspector = sa.inspect(sync_conn)

    if not inspector.has_table(table_name):
        return None

    dialect_name = sync_conn.dialect.name
    introspection = resolve_dialect_by_vendor(dialect_name)

    columns: list[dict[str, t.Any]] = []
    pk_cols: set[str] = set()

    pk_info = inspector.get_pk_constraint(table_name)
    if pk_info:
        pk_cols = set(pk_info.get("constrained_columns", []))

    fk_info = inspector.get_foreign_keys(table_name)
    fk_map: dict[str, dict[str, t.Any]] = {}
    for fk in fk_info:
        constrained = fk.get("constrained_columns", [])
        referred_table = fk.get("referred_table", "")
        referred_cols = fk.get("referred_columns", [])
        for col_name in constrained:
            fk_map[col_name] = {
                "target_table": referred_table,
                "column": referred_cols[0] if referred_cols else "id",
            }

    for col in inspector.get_columns(table_name):
        col_name = col["name"]
        col_type_str = str(col["type"])
        col_dict: dict[str, t.Any] = {
            "name": col_name,
            "type": col_type_str,
            "nullable": col.get("nullable", True),
        }
        if col_name in pk_cols:
            col_dict["primary_key"] = True
            col_dict["autoincrement"] = introspection.detect_autoincrement(
                col_name, col_type_str, col
            )
        if col.get("unique"):
            col_dict["unique"] = True
        default = col.get("default")
        if default is not None and not callable(default):
            col_dict["default"] = default
        else:
            col_dict["default"] = None

        fk_entry = fk_map.get(col_name)
        if fk_entry:
            col_dict["target_table"] = fk_entry["target_table"]

        columns.append(col_dict)

    columns.sort(key=lambda c: c["name"])

    dialect_unique_cols = introspection.detect_unique_columns(sync_conn, table_name)
    if dialect_unique_cols:
        for col in columns:
            if col["name"] in dialect_unique_cols:
                col["unique"] = True

    indexes: list[dict[str, t.Any]] = []

    unique_constraint_cols: list[frozenset[str]] = []
    named_unique_constraints: list[dict[str, t.Any]] = []
    try:
        for constraint in inspector.get_unique_constraints(table_name):
            col_names = frozenset(constraint.get("column_names", []))
            ck_name = constraint.get("name", "")
            if col_names:
                unique_constraint_cols.append(col_names)
                if ck_name and not ck_name.startswith("uniq_"):
                    named_unique_constraints.append({
                        "name": ck_name,
                        "type": "UNIQUE",
                        "fields": sorted(col_names),
                    })
    except NotImplementedError:
        logger.debug(
            "Dialect does not support unique constraint introspection "
            "for table '%s'; unique_together diffing will be skipped",
            table_name,
        )

    unique_constraint_cols_flat: set[str] = set()
    for cols in unique_constraint_cols:
        if len(cols) == 1:
            unique_constraint_cols_flat.update(cols)
    # Set unique=True for columns found via get_unique_constraints()
    for col_name in unique_constraint_cols_flat:
        for col in columns:
            if col["name"] == col_name:
                col["unique"] = True
                break
    # Also check unique indexes that weren't covered by get_unique_constraints()
    for idx in inspector.get_indexes(table_name):
        idx_cols = frozenset(idx.get("column_names", []))
        if idx.get("unique") and len(idx_cols) == 1:
            col_name = next(iter(idx_cols))
            if col_name not in unique_constraint_cols_flat:
                for col in columns:
                    if col["name"] == col_name:
                        col["unique"] = True
                        break

    unique_column_names: set[str] = {
        c["name"] for c in columns if c.get("unique")
    }

    for idx in inspector.get_indexes(table_name):
        idx_cols = frozenset(idx.get("column_names", []))
        if idx.get("unique") and idx_cols in unique_constraint_cols:
            continue
        if idx.get("unique") and len(idx_cols) > 1:
            unique_constraint_cols.append(idx_cols)
            idx_name = idx.get("name", "")
            if idx_name and not idx_name.startswith("uniq_"):
                named_unique_constraints.append({
                    "name": idx_name,
                    "type": "UNIQUE",
                    "fields": sorted(idx_cols),
                })
            continue
        if (
            idx.get("unique")
            and len(idx_cols) == 1
            and next(iter(idx_cols)) in unique_column_names
        ):
            continue
        indexes.append(
            {
                "name": idx["name"],
                "fields": list(idx["column_names"]),
            }
        )
    indexes.sort(key=lambda x: x.get("name") or str(x.get("fields")))

    unique_together: list[list[str]] = []
    named_ut_cols = {frozenset(c["fields"]) for c in named_unique_constraints}
    for cols in unique_constraint_cols:
        if len(cols) > 1 and cols not in named_ut_cols:
            unique_together.append(sorted(cols))
    unique_together.sort()

    # Separate composite non-unique indexes (index_together) from single-column indexes.
    index_together: list[list[str]] = []
    single_indexes: list[dict[str, t.Any]] = []
    for idx in indexes:
        if len(idx["fields"]) > 1:
            index_together.append(sorted(idx["fields"]))
        else:
            single_indexes.append(idx)
    index_together.sort()
    indexes = single_indexes
    indexes.sort(key=lambda x: x.get("name") or str(x.get("fields")))

    constraints: list[dict[str, t.Any]] = []

    try:
        for ck in inspector.get_check_constraints(table_name):
            ck_name = ck.get("name")
            if not ck_name:
                continue
            constraints.append({
                "name": ck_name,
                "type": "CHECK",
                "check": ck.get("sqltext", ""),
            })
    except NotImplementedError:
        logger.debug(
            "Dialect does not support check constraint introspection "
            "for table '%s'; CHECK constraint diffing will be skipped",
            table_name,
        )

    for cols in unique_constraint_cols:
        if len(cols) == 1:
            col_list = sorted(cols)
            constraints.append({
                "name": f"uniq_{table_name}_{'_'.join(col_list)}",
                "type": "UNIQUE",
                "fields": col_list,
            })

    constraints.extend(named_unique_constraints)
    constraints.sort(key=lambda c: c["name"])

    return {
        "columns": columns,
        "indexes": indexes,
        "unique_together": unique_together,
        "index_together": index_together,
        "constraints": constraints,
    }


async def introspect_db_schema(
    table_names: list[str] | None = None,
    db_alias: str = "default",
) -> dict[str, dict[str, t.Any]]:
    """Introspect the live database schema into a state dict.

    Args:
        table_names: Optional list of table names to introspect.  If
            None, all tables in the database are introspected.
        db_alias: Database alias to introspect.

    Returns:
        State dict mapping table names to schema data.
    """
    engine = await get_async_engine(db_alias)
    state: dict[str, dict[str, t.Any]] = {}

    def sync_introspect(sync_conn: sa.Connection) -> dict[str, dict[str, t.Any]]:
        inspector = sa.inspect(sync_conn)
        names = table_names or list(inspector.get_table_names())
        result: dict[str, dict[str, t.Any]] = {}
        for name in names:
            table_state = introspect_table_sync(sync_conn, name)
            if table_state is not None:
                result[name] = table_state
        return result

    async with engine.connect() as conn:
        state = await conn.run_sync(sync_introspect)

    return state
