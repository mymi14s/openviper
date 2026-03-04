"""Initial migration for openviper tasks.

Creates ``openviper_task_results`` — the result-tracking table used by
:mod:`openviper.tasks.results` to store every task's lifecycle state.

Note: the table is also created automatically (CREATE TABLE IF NOT EXISTS)
by the results module on first use, so running this migration is optional
but recommended for clean schema management.
"""

from openviper.db.migrations import executor as migrations

dependencies: list = []

operations = [
    migrations.CreateTable(
        table_name="openviper_task_results",
        columns=[
            {
                "name": "id",
                "type": "INTEGER",
                "nullable": False,
                "primary_key": True,
                "autoincrement": True,
            },
            # ── Identity ──────────────────────────────────────────────────
            {
                "name": "message_id",
                "type": "VARCHAR(64)",
                "nullable": False,
                "unique": True,
            },
            {
                "name": "actor_name",
                "type": "VARCHAR(255)",
                "nullable": False,
                "default": "unknown",
            },
            {
                "name": "queue_name",
                "type": "VARCHAR(100)",
                "nullable": False,
                "default": "unknown",
            },
            # ── State ─────────────────────────────────────────────────────
            # pending | running | success | failure | skipped | dead
            {
                "name": "status",
                "type": "VARCHAR(20)",
                "nullable": False,
                "default": "pending",
            },
            {
                "name": "retries",
                "type": "INTEGER",
                "nullable": False,
                "default": 0,
            },
            # ── Payload ───────────────────────────────────────────────────
            {"name": "args", "type": "TEXT", "nullable": True},
            {"name": "kwargs", "type": "TEXT", "nullable": True},
            # ── Outcome ───────────────────────────────────────────────────
            {"name": "result", "type": "TEXT", "nullable": True},
            {"name": "error", "type": "TEXT", "nullable": True},
            {"name": "traceback", "type": "TEXT", "nullable": True},
            # ── Timestamps ────────────────────────────────────────────────
            {"name": "enqueued_at", "type": "DATETIME", "nullable": True},
            {"name": "started_at", "type": "DATETIME", "nullable": True},
            {"name": "completed_at", "type": "DATETIME", "nullable": True},
        ],
    ),
]
