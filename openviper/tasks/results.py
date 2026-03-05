"""Task result storage and query layer.

All task state is kept in the ``openviper_task_results`` table, which is
created automatically on first use (CREATE TABLE IF NOT EXISTS) so no extra
migration is required to start tracking.

Query API
---------
Async helpers (call from inside a coroutine / ASGI handler)::

    from openviper.tasks.results import get_task_result, list_task_results

    result = await get_task_result("message-uuid")
    # {"message_id": "...", "status": "success", "result": "...", ...}

    recent = await list_task_results(status="failure", limit=20)

Sync helper (call from middleware / management commands)::

    from openviper.tasks.results import get_task_result_sync
    row = get_task_result_sync("message-uuid")

Write helper (used internally by TaskTrackingMiddleware)::

    from openviper.tasks.results import upsert_result
    upsert_result(message_id="...", status="running", started_at=datetime.now(utc))

Column reference
----------------
* ``message_id``   – Dramatiq UUID (primary key for lookups)
* ``actor_name``   – fully-qualified actor name, e.g. ``posts.models.moderate``
* ``queue_name``   – queue the message was sent to
* ``status``       – pending | running | success | failure | skipped | dead
* ``args``         – JSON-encoded positional arguments
* ``kwargs``       – JSON-encoded keyword arguments
* ``result``       – JSON-encoded return value (success only)
* ``error``        – str(exception) on failure
* ``traceback``    – full traceback on failure
* ``retries``      – number of retries consumed so far
* ``enqueued_at``  – UTC datetime when the message was enqueued
* ``started_at``   – UTC datetime when the worker picked it up
* ``completed_at`` – UTC datetime when it finished (success, failure, or skip)
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import logging
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy import create_engine

logger = logging.getLogger("openviper.tasks")

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_metadata = sa.MetaData()

_table = sa.Table(
    "openviper_task_results",
    _metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column(
        "message_id",
        sa.String(64),
        nullable=False,
        unique=True,
        index=True,
    ),
    sa.Column("actor_name", sa.String(255), nullable=False, index=True, default="unknown"),
    sa.Column("queue_name", sa.String(100), nullable=False, default="unknown"),
    sa.Column("status", sa.String(20), nullable=False, default="pending"),
    sa.Column("args", sa.JSON, nullable=True),
    sa.Column("kwargs", sa.JSON, nullable=True),
    sa.Column("result", sa.JSON, nullable=True),
    sa.Column("error", sa.Text, nullable=True),
    sa.Column("traceback", sa.Text, nullable=True),
    sa.Column("retries", sa.Integer, nullable=False, default=0),
    sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
)

# ---------------------------------------------------------------------------
# Engine singleton
# ---------------------------------------------------------------------------

_engine: Any = None
_upsert_fn: Any = None  # set when engine is first created; dialect-specific
_engine_lock = threading.Lock()

# Async→sync driver mapping for databases other than PostgreSQL.
_ASYNC_TO_SYNC_SIMPLE = [
    ("sqlite+aiosqlite://", "sqlite://"),
    ("mysql+aiomysql://", "mysql+pymysql://"),
]

# Sync driver preference order for PostgreSQL.
_PG_ASYNC_PREFIXES = ("postgresql+asyncpg://", "postgres+asyncpg://")
_PG_SYNC_DRIVERS = ("psycopg2", "pg8000", "psycopg")


def _to_sync_url(url: str) -> str:
    """Convert an async-driver database URL to its synchronous equivalent."""
    # Simple one-to-one replacements (SQLite, MySQL).
    for async_prefix, sync_prefix in _ASYNC_TO_SYNC_SIMPLE:
        if url.startswith(async_prefix):
            return sync_prefix + url[len(async_prefix) :]

    # PostgreSQL: detect the first available synchronous driver.
    for async_prefix in _PG_ASYNC_PREFIXES:
        if url.startswith(async_prefix):
            rest = url[len(async_prefix) :]
            for driver in _PG_SYNC_DRIVERS:
                try:
                    importlib.import_module(driver)
                    return f"postgresql+{driver}://{rest}"
                except ModuleNotFoundError:
                    continue
            raise RuntimeError(
                "No synchronous PostgreSQL driver found for task result "
                "tracking. The task results DB requires a synchronous driver "
                "alongside asyncpg. Install one of:\n"
                "  pip install psycopg2-binary   # recommended\n"
                "  pip install pg8000            # pure-Python alternative\n"
                "Or point TASKS['results_db_url'] at a SQLite URL to keep "
                "results separate from your main database."
            )

    # Unknown or already-sync URL — pass through unchanged.
    return url


def _get_engine() -> Any:
    global _engine, _upsert_fn
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine

        url = _resolve_db_url()
        if not url:
            raise RuntimeError(
                "Task result tracking requires a DATABASE_URL.  "
                "Set it in settings or add 'results_db_url' to TASKS."
            )

        url = _to_sync_url(url)

        # pool_size=10 accommodates the default 8 worker threads with headroom;
        # max_overflow=5 allows short bursts without exhausting the DB.
        engine_kwargs: dict[str, Any] = {"pool_pre_ping": True}
        if ":memory:" not in url and "mode=memory" not in url:
            engine_kwargs["pool_size"] = 10
            engine_kwargs["max_overflow"] = 5

        engine = create_engine(url, **engine_kwargs)
        # Ensure the table exists — idempotent, safe to call repeatedly.
        # Assign to _engine only after create_all succeeds so a failed attempt
        # doesn't leave a broken engine in the singleton cache.
        _metadata.create_all(engine, checkfirst=True)
        _engine = engine
        _upsert_fn = _build_upsert_fn(engine.dialect.name)
        logger.debug("Task results engine initialised: %s", url.split("@")[-1])
    return _engine


def _resolve_db_url() -> str:
    """Return the DB URL to use for task results."""
    try:
        from openviper.conf import settings

        task_cfg: dict[str, Any] = getattr(settings, "TASKS", {}) or {}
        # Allow a dedicated result DB; fall back to the main DB.
        return (
            task_cfg.get("results_db_url")
            or task_cfg.get("RESULTS_DB_URL")
            or getattr(settings, "DATABASE_URL", "")
            or ""
        )
    except Exception:
        return ""


def reset_engine() -> None:
    """Dispose and forget the engine.  Primarily for tests."""
    global _engine, _upsert_fn
    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
            _engine = None
        _upsert_fn = None


# ---------------------------------------------------------------------------
# Write (synchronous — called from middleware / management commands)
# ---------------------------------------------------------------------------


def _build_upsert_fn(dialect_name: str) -> Any:
    """Return a dialect-specific upsert callable for the result table.

    PostgreSQL and SQLite both support ``INSERT ... ON CONFLICT DO UPDATE``,
    letting us write-or-update in a single round-trip.  MySQL uses
    ``ON DUPLICATE KEY UPDATE``.  Unknown dialects fall back to the
    classic SELECT + INSERT/UPDATE (two round-trips but universally portable).

    The returned function has the signature::

        upsert(conn, message_id: str, fields: dict) -> None
    """
    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as _ins

        def _pg(conn: Any, message_id: str, fields: dict[str, Any]) -> None:
            data = {
                "actor_name": "unknown",
                "queue_name": "unknown",
                "status": "pending",
                **fields,
                "message_id": message_id,
            }
            update_data = {k: v for k, v in fields.items() if k != "message_id"}
            stmt = _ins(_table).values(**data)
            stmt = (
                stmt.on_conflict_do_update(index_elements=["message_id"], set_=update_data)
                if update_data
                else stmt.on_conflict_do_nothing()
            )
            conn.execute(stmt)

        return _pg

    if dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_ins

        def _sqlite(conn: Any, message_id: str, fields: dict[str, Any]) -> None:
            data = {
                "actor_name": "unknown",
                "queue_name": "unknown",
                "status": "pending",
                **fields,
                "message_id": message_id,
            }
            update_data = {k: v for k, v in fields.items() if k != "message_id"}
            stmt = sqlite_ins(_table).values(**data)
            stmt = (
                stmt.on_conflict_do_update(index_elements=["message_id"], set_=update_data)
                if update_data
                else stmt.on_conflict_do_nothing()
            )
            conn.execute(stmt)

        return _sqlite

    if dialect_name in ("mysql", "mariadb"):
        from sqlalchemy.dialects.mysql import insert as mysql_ins

        def _mysql(conn: Any, message_id: str, fields: dict[str, Any]) -> None:
            data = {
                "actor_name": "unknown",
                "queue_name": "unknown",
                "status": "pending",
                **fields,
                "message_id": message_id,
            }
            update_data = {k: v for k, v in fields.items() if k != "message_id"}
            stmt: Any = mysql_ins(_table).values(**data)
            if update_data:
                conn.execute(stmt.on_duplicate_key_update(**update_data))
            else:
                conn.execute(stmt.prefix_with("IGNORE"))

        return _mysql

    # Generic fallback: SELECT then INSERT or UPDATE (2 round-trips).
    def _generic(conn: Any, message_id: str, fields: dict[str, Any]) -> None:
        existing = conn.execute(
            sa.select(_table.c.id).where(_table.c.message_id == message_id)
        ).fetchone()
        if existing:
            update_data = {k: v for k, v in fields.items() if k != "message_id"}
            if update_data:
                conn.execute(
                    _table.update().where(_table.c.message_id == message_id).values(**update_data)
                )
        else:
            conn.execute(
                _table.insert().values(
                    actor_name="unknown",
                    queue_name="unknown",
                    status="pending",
                    **fields,
                    message_id=message_id,
                )
            )

    return _generic


def upsert_result(message_id: str, **fields: Any) -> None:
    """Create or update a task result row.

    Only the supplied *fields* are written; omitted columns keep their
    existing value (or their column default if this is a new row).
    Uses a native single-statement UPSERT on PostgreSQL, SQLite, and MySQL.
    """
    try:
        engine = _get_engine()
    except RuntimeError as exc:
        logger.debug("upsert_result skipped: %s", exc)
        return

    # Serialise dict / list fields to JSON strings.
    for key in ("args", "kwargs"):
        if key in fields and not isinstance(fields[key], str):
            try:
                fields[key] = json.dumps(fields[key])
            except Exception:
                fields[key] = repr(fields[key])

    try:
        with engine.begin() as conn:
            _upsert_fn(conn, message_id, fields)
    except Exception as exc:
        logger.warning("upsert_result failed for %s: %s", message_id, exc)


def batch_upsert_results(events: list[tuple[str, dict[str, Any]]]) -> None:
    """Write multiple task result rows in a single database transaction.

    Accepts a list of ``(message_id, fields)`` pairs and executes one
    UPSERT per pair, all within a single ``engine.begin()`` transaction.
    This is the batch counterpart to :func:`upsert_result` and is
    intended for use by :class:`~openviper.tasks.middleware._EventBuffer`.

    Args:
        events: List of ``(message_id, fields)`` tuples.  *fields* follows
            the same conventions as :func:`upsert_result` — omitted columns
            keep their existing value or column default.
    """
    if not events:
        return
    try:
        engine = _get_engine()
    except RuntimeError as exc:
        logger.debug("batch_upsert_results skipped: %s", exc)
        return

    # Serialise dict / list fields to JSON strings (mutate a copy per event).
    prepared: list[tuple[str, dict[str, Any]]] = []
    for message_id, raw_fields in events:
        fields = dict(raw_fields)
        for key in ("args", "kwargs"):
            if key in fields and not isinstance(fields[key], str):
                try:
                    fields[key] = json.dumps(fields[key])
                except Exception:
                    fields[key] = repr(fields[key])
        prepared.append((message_id, fields))

    try:
        with engine.begin() as conn:
            for message_id, fields in prepared:
                _upsert_fn(conn, message_id, fields)
    except Exception as exc:
        logger.warning("batch_upsert_results failed (%d events): %s", len(events), exc)


# ---------------------------------------------------------------------------
# Read — synchronous
# ---------------------------------------------------------------------------


def get_task_result_sync(message_id: str) -> dict[str, Any] | None:
    """Return a single task result row as a dict, or ``None`` if not found."""
    try:
        engine = _get_engine()
    except RuntimeError:
        return None

    with engine.connect() as conn:
        row = conn.execute(sa.select(_table).where(_table.c.message_id == message_id)).fetchone()

    if row is None:
        return None
    return _row_to_dict(row)


def list_task_results_sync(
    *,
    status: str | None = None,
    actor_name: str | None = None,
    queue_name: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return a list of task result rows matching the given filters."""
    try:
        engine = _get_engine()
    except RuntimeError:
        return []

    stmt = sa.select(_table).order_by(_table.c.enqueued_at.desc())
    if status:
        stmt = stmt.where(_table.c.status == status)
    if actor_name:
        stmt = stmt.where(_table.c.actor_name == actor_name)
    if queue_name:
        stmt = stmt.where(_table.c.queue_name == queue_name)
    stmt = stmt.limit(limit).offset(offset)

    with engine.connect() as conn:
        rows = conn.execute(stmt).fetchall()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Read — async wrappers (for use inside ASGI handlers / coroutines)
# ---------------------------------------------------------------------------


async def get_task_result(message_id: str) -> dict[str, Any] | None:
    """Async wrapper around :func:`get_task_result_sync`."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, get_task_result_sync, message_id)


async def list_task_results(
    *,
    status: str | None = None,
    actor_name: str | None = None,
    queue_name: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Async wrapper around :func:`list_task_results_sync`."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: list_task_results_sync(
            status=status,
            actor_name=actor_name,
            queue_name=queue_name,
            limit=limit,
            offset=offset,
        ),
    )


# ---------------------------------------------------------------------------
# Management — synchronous
# ---------------------------------------------------------------------------


def delete_task_result(message_id: str) -> bool:
    """Delete a task result record. Returns True if a record was deleted."""
    try:
        engine = _get_engine()
    except RuntimeError:
        return False

    with engine.begin() as conn:
        res = conn.execute(sa.delete(_table).where(_table.c.message_id == message_id))
        return bool(res.rowcount > 0)


def clean_old_results(days: int = 7) -> int:
    """Delete task results older than the given number of days.

    Args:
        days: Rows with ``completed_at`` older than this many days are removed.

    Returns:
        Number of rows deleted.
    """
    try:
        engine = _get_engine()
    except RuntimeError:
        return 0

    cutoff = datetime.now(UTC) - timedelta(days=days)
    with engine.begin() as conn:
        res = conn.execute(sa.delete(_table).where(_table.c.completed_at < cutoff))
        return int(res.rowcount or 0)


# ---------------------------------------------------------------------------
# Management — async wrappers
# ---------------------------------------------------------------------------


async def get_task_stats() -> dict[str, int]:
    """Return counts of tasks grouped by status."""
    try:
        engine = _get_engine()
    except RuntimeError:
        return {"total": 0, "success": 0, "failure": 0, "pending": 0, "running": 0}

    stmt = sa.select(_table.c.status, sa.func.count(_table.c.id)).group_by(_table.c.status)

    loop = asyncio.get_running_loop()

    def _get() -> dict[str, int]:
        with engine.connect() as conn:
            return dict(conn.execute(stmt).fetchall())

    counts = await loop.run_in_executor(None, _get)

    stats = {
        "success": counts.get("success", 0),
        "failure": counts.get("failure", 0),
        "pending": counts.get("pending", 0),
        "running": counts.get("running", 0),
    }
    stats["total"] = sum(stats.values())
    return stats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: Any) -> dict[str, Any]:
    d = dict(row._mapping)
    # Deserialise JSON columns back to Python objects for convenience.
    for key in ("args", "kwargs"):
        if isinstance(d.get(key), str):
            with contextlib.suppress(Exception):
                d[key] = json.loads(d[key])
    # Normalise datetime objects to ISO strings.
    for key in ("enqueued_at", "started_at", "completed_at"):
        val = d.get(key)
        if isinstance(val, datetime):
            d[key] = val.isoformat()
    return d
