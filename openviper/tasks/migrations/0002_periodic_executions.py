"""Add indexes for task result lookups."""

from __future__ import annotations

from openviper.db.migrations import executor as migrations  # noqa: E402

dependencies: list[tuple[str, str]] = [("openviper.tasks", "0001_initial")]

operations = [
    migrations.CreateIndex(
        table_name="openviper_task_result",
        index_name="ix_task_result_actor_name",
        columns=["actor_name"],
    ),
    migrations.CreateIndex(
        table_name="openviper_task_result",
        index_name="ix_task_result_status",
        columns=["status"],
    ),
    migrations.CreateIndex(
        table_name="openviper_task_result",
        index_name="ix_task_result_created_at",
        columns=["created_at"],
    ),
    migrations.CreateIndex(
        table_name="openviper_scheduled_job",
        index_name="ix_scheduled_job_status",
        columns=["status"],
    ),
    migrations.AddColumn(
        table_name="openviper_scheduled_job",
        column_name="cron_description",
        column_type="VARCHAR",
        nullable=True,
    ),
    migrations.AddColumn(
        table_name="openviper_scheduled_job",
        column_name="last_enqueued_at",
        column_type="TIMESTAMP",
        nullable=True,
    ),
]


async def up() -> None:
    pass


async def down() -> None:
    pass
