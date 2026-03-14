from openviper.admin import ModelAdmin, register
from openviper.tasks.models import TaskResult


@register(TaskResult)
class TaskResultAdmin(ModelAdmin):
    list_display = [
        "message_id",
        "actor_name",
        "queue_name",
        "status",
        "retries",
        "enqueued_at",
        "started_at",
        "completed_at",
    ]
    search_fields = ["message_id", "actor_name", "queue_name"]
    list_filter = ["status", "enqueued_at", "started_at", "completed_at"]
    list_display_styles = {"status": "status_badge"}
