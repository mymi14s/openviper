"""Schema synchronization orchestrator.

Reads JSON schema files as the desired state, introspects the live
database as the actual state, computes the diff, and applies the
resulting operations.
"""

from __future__ import annotations

import logging
import re
import typing as t
from pathlib import Path

import orjson
import sqlalchemy as sa

from openviper.db.migrations.executor import (
    AddColumn,
    AlterColumn,
    CreateIndex,
    CreateTable,
    DropTable,
    RemoveColumn,
    RemoveIndex,
    RenameColumn,
)
from openviper.db.migrations.writer import diff_states
from openviper.db.patches.runner import discover_patches, run_patches
from openviper.db.schemas.detect import clean_change_metadata
from openviper.db.schemas.introspect import get_async_engine, introspect_db_schema
from openviper.db.schemas.json_reader import (
    discover_json_schemas,
    read_all_json_schemas,
    read_all_raw_schemas,
)

logger = logging.getLogger("openviper.schemas")


class SchemaSync:
    """Synchronize JSON schema files to the live database.

    Stateless and idempotent: running ``sync`` twice produces no changes
    on the second run because the diff is empty.
    """

    def __init__(
        self,
        resolved_apps: dict[str, str] | None = None,
    ) -> None:
        self.resolved_apps = resolved_apps

    async def sync(
        self,
        target_app: str | None = None,
        *,
        verbose: bool = True,
        database: str = "default",
    ) -> list[str]:
        """Apply pending schema changes by diffing JSON vs live DB.

        Args:
            target_app: If set, only sync this app's tables.
            verbose: Enable terminal logging.
            database: Database alias.

        Returns:
            List of applied operation descriptions.
        """
        desired_state = discover_json_schemas(resolved_apps=self.resolved_apps)

        if target_app:
            desired_state = self.filter_by_app(desired_state, target_app)

        if not desired_state:
            if verbose:
                print("  No schema files found.")
            return []

        discover_patches(resolved_apps=self.resolved_apps)

        await run_patches(post_migrate=False, verbose=verbose, database=database)

        table_names = list(desired_state.keys())
        actual_state = await introspect_db_schema(table_names=table_names, db_alias=database)

        # Pass raw (un-normalised) state to diff_states - it normalises
        # internally and keeps raw copies for CreateTable/AddColumn which
        # need the original type strings (e.g. VARCHAR(255) not TEXT).
        ops = diff_states(desired_state, actual_state)

        applied: list[str] = []

        if not ops:
            print("\n  No schema changes to apply.\n")

        if ops:
            table_labels = self.build_table_labels()

            engine = await get_async_engine(database)
            deferred_fk_stmts: list[str] = []
            printed_header = False
            printed_models: set[str] = set()

            for op in ops:
                desc = self.describe_operation(op)

                try:
                    async with engine.begin() as conn:
                        for sql_stmt in op.forward_sql():
                            stmt = sa.text(sql_stmt) if isinstance(sql_stmt, str) else sql_stmt
                            await conn.execute(stmt)
                        if isinstance(op, CreateTable):
                            deferred_fk_stmts.extend(op.deferred_fk_stmts())

                    # Print header and model label only for ops that actually ran.
                    if not printed_header:
                        print("Migrating...\n")
                        printed_header = True
                    label = table_labels.get(self.op_table_name(op), self.op_table_name(op))
                    if label not in printed_models:
                        print(f"  {label}")
                        printed_models.add(label)
                    if verbose:
                        print(f"    -> {desc}")

                    applied.append(desc)
                except Exception as exc:
                    err_str = str(exc).lower()
                    if (
                        isinstance(op, CreateIndex)
                        and (
                            "1061" in err_str
                            or "duplicate key name" in err_str
                            or "already exists" in err_str
                        )
                    ):
                        logger.debug(
                            "Index '%s' on '%s' already exists, skipping",
                            op.index_name, op.table_name,
                        )
                        continue
                    if (
                        isinstance(op, RemoveIndex)
                        and ("1553" in err_str or "needed in a foreign key" in err_str)
                    ):
                        logger.debug(
                            "Index '%s' on '%s' is FK-backed, skipping removal",
                            op.index_name, op.table_name,
                        )
                        continue
                    logger.error("Failed to apply %s: %s", desc, exc)
                    raise

            if not applied:
                print("\n  No schema changes to apply.\n")

            for fk_stmt in deferred_fk_stmts:
                try:
                    async with engine.begin() as conn:
                        await conn.execute(sa.text(fk_stmt))
                except Exception as fk_err:
                    err_str = str(fk_err).lower()
                    if "already exists" in err_str or "duplicate" in err_str:
                        logger.debug("Deferred FK already exists: %s", fk_stmt)
                    elif (
                        "1785" in err_str
                        or "multiple cascade paths" in err_str
                        or "cycles or multiple cascade" in err_str
                    ):
                        fallback = re.sub(
                            r'\bON\s+DELETE\s+CASCADE\b',
                            'ON DELETE NO ACTION',
                            fk_stmt,
                            flags=re.IGNORECASE,
                        )
                        if fallback != fk_stmt:
                            logger.info(
                                "MSSQL FK cascade cycle (1785) - retrying with NO ACTION: %s",
                                fk_stmt.split('\n')[0][:120],
                            )
                            try:
                                async with engine.begin() as conn:
                                    await conn.execute(sa.text(fallback))
                            except Exception as retry_err:
                                logger.warning(
                                    "Could not apply deferred FK"
                                    " (NO ACTION fallback): %s",
                                    retry_err,
                                )
                        else:
                            logger.warning("Could not apply deferred FK: %s", fk_err)
                    else:
                        logger.warning("Could not apply deferred FK: %s", fk_err)

            self.clean_schemas_after_sync()

        await run_patches(post_migrate=True, verbose=verbose, database=database)

        return applied

    def clean_schemas_after_sync(self) -> None:
        """Remove transient change metadata from JSON schema files."""
        if not self.resolved_apps:
            return
        for app_path in self.resolved_apps.values():
            schemas_dir = Path(app_path) / "schemas"
            if not schemas_dir.is_dir():
                continue
            for json_file in sorted(schemas_dir.glob("*.json")):
                schema = t.cast("dict[str, t.Any]", orjson.loads(json_file.read_bytes()))
                cleaned = clean_change_metadata(schema)
                if cleaned != schema:
                    json_file.write_bytes(orjson.dumps(cleaned, option=orjson.OPT_INDENT_2))

    def filter_by_app(
        self,
        state: dict[str, dict[str, t.Any]],
        app_name: str,
    ) -> dict[str, dict[str, t.Any]]:
        """Filter state dict to only tables belonging to the given app."""
        if not self.resolved_apps:
            return state

        app_path = self.resolved_apps.get(app_name)
        if not app_path:
            return state

        schemas_dir = Path(app_path) / "schemas"
        if not schemas_dir.is_dir():
            return {}
        return read_all_json_schemas(str(schemas_dir))

    def build_table_labels(self) -> dict[str, str]:
        """Build a mapping of table_name to 'app.Model' labels.

        If the app name is empty, only the model name is used.
        """
        labels: dict[str, str] = {}
        if not self.resolved_apps:
            return labels
        for app_path in self.resolved_apps.values():
            schemas_dir = Path(app_path) / "schemas"
            if not schemas_dir.is_dir():
                continue
            raw = read_all_raw_schemas(str(schemas_dir))
            for table_name, schema in raw.items():
                app = schema.get("app", "")
                model = schema.get("model", table_name)
                if app:
                    labels[table_name] = f"{app}.{model}"
                else:
                    labels[table_name] = model
        return labels

    def op_table_name(self, op: t.Any) -> str:
        """Extract the table name from an operation."""
        return getattr(op, "table_name", "")

    def describe_operation(self, op: t.Any) -> str:
        """Return a human-readable description of an operation."""
        if isinstance(op, CreateTable):
            return f"Create table '{op.table_name}'"
        if isinstance(op, DropTable):
            return f"Drop table '{op.table_name}'"
        if isinstance(op, AddColumn):
            return f"Add column '{op.column_name}' to '{op.table_name}'"
        if isinstance(op, RemoveColumn):
            return f"Remove column '{op.column_name}' from '{op.table_name}'"
        if isinstance(op, RenameColumn):
            return f"Rename column '{op.old_name}' to '{op.new_name}' on '{op.table_name}'"
        if isinstance(op, AlterColumn):
            return f"Alter column '{op.column_name}' on '{op.table_name}'"
        if isinstance(op, CreateIndex):
            return f"Create index '{op.index_name}' on '{op.table_name}'"
        if isinstance(op, RemoveIndex):
            return f"Remove index '{op.index_name}' from '{op.table_name}'"
        return repr(op)
