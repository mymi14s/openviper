"""Initial migration - create task result tables."""

from __future__ import annotations

from openviper.db.migrations import executor as migrations

dependencies: list[tuple[str, str]] = []

operations = [
    migrations.CreateTable(
        table_name="openviper_task_result",
        columns=[
            {
                "name": "id",
                "type": "INTEGER",
                "nullable": False,
                "primary_key": True,
                "autoincrement": True,
            },
            {"name": "message_id", "type": "VARCHAR", "nullable": False, "unique": True},
            {"name": "actor_name", "type": "VARCHAR", "nullable": False},
            {"name": "queue", "type": "VARCHAR", "nullable": False},
            {"name": "arguments", "type": "TEXT", "nullable": True},
            {"name": "return_value", "type": "TEXT", "nullable": True},
            {"name": "error_traceback", "type": "TEXT", "nullable": True},
            {"name": "status", "type": "VARCHAR", "nullable": False},
            {"name": "retries", "type": "INTEGER", "nullable": False},
            {"name": "duration_ms", "type": "BIGINT", "nullable": True},
            {"name": "created_at", "type": "DATETIME", "nullable": True},
            {"name": "updated_at", "type": "DATETIME", "nullable": True},
        ],
    ),
    migrations.CreateTable(
        table_name="openviper_scheduled_job",
        columns=[
            {
                "name": "id",
                "type": "INTEGER",
                "nullable": False,
                "primary_key": True,
                "autoincrement": True,
            },
            {"name": "app", "type": "VARCHAR", "nullable": False},
            {"name": "name", "type": "VARCHAR", "nullable": False, "unique": True},
            {"name": "schedule", "type": "VARCHAR", "nullable": False},
            {"name": "status", "type": "VARCHAR", "nullable": False},
            {"name": "trigger_source", "type": "VARCHAR", "nullable": False},
        ],
    ),
]


async def up() -> None:
    pass


async def down() -> None:
    pass
