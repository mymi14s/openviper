"""Admin integration for ``TaskResult`` and ``ScheduledJob`` models.

Includes a ``RunNowAction`` for immediate task dispatch.
"""

from __future__ import annotations

import typing as t

from openviper.admin.actions import ActionResult, AdminAction, register_action
from openviper.admin.decorators import register
from openviper.admin.options import ModelAdmin
from openviper.tasks.decorators import enqueue_task
from openviper.tasks.models import ScheduledJob, TaskResult

if t.TYPE_CHECKING:
    from openviper.db.models import QuerySet
    from openviper.http.request import Request


class RunNowAction(AdminAction):
    """Enqueue the selected scheduled job for immediate execution."""

    name = "run_now"
    description = "Run selected job now"

    async def execute(
        self,
        queryset: QuerySet,
        request: Request,
        model_admin: ModelAdmin | None = None,
    ) -> ActionResult:
        """Enqueue each selected job for immediate execution."""
        count = 0
        errors: list[str] = []
        async for obj in queryset:
            actor_name = getattr(obj, "name", None)
            if actor_name:
                try:
                    enqueue_task(actor_name, (), {}, queue_name="default")
                    count += 1
                except Exception as exc:
                    errors.append(f"{actor_name}: {exc}")
        return ActionResult(
            success=len(errors) == 0,
            count=count,
            message=f"Enqueued {count} job(s).",
            errors=errors or None,
        )


register_action(RunNowAction)


@register(TaskResult)
class TaskResultAdmin(ModelAdmin):
    """Admin configuration for task execution results."""

    list_display = [
        "message_id",
        "actor_name",
        "queue",
        "status",
        "retries",
        "duration_ms",
        "created_at",
    ]
    list_filter = ["status", "queue", "actor_name"]
    search_fields = ["actor_name", "message_id"]
    readonly_fields = ["message_id", "created_at", "updated_at"]
    ordering = ["-created_at"]


@register(ScheduledJob)
class ScheduledJobAdmin(ModelAdmin):
    """Admin configuration for scheduled job records."""

    list_display = [
        "name",
        "app",
        "schedule",
        "cron_description",
        "status",
        "trigger_source",
    ]
    list_filter = ["status", "trigger_source", "app"]
    search_fields = ["name", "app"]
    actions = [RunNowAction]
