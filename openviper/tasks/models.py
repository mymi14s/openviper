"""Task result persistence models.

Defines ``TaskResult`` and ``ScheduledJob`` as ORM models for tracking
task execution state and periodic schedule synchronisation.
"""

from __future__ import annotations

from openviper.db import fields
from openviper.db.models import Model

TASK_STATUS_CHOICES: list[tuple[str, str]] = [
    ("pending", "Pending"),
    ("running", "Running"),
    ("success", "Success"),
    ("failure", "Failure"),
    ("skipped", "Skipped"),
    ("dead", "Dead"),
]
TRIGGER_SOURCE_CHOICES: list[tuple[str, str]] = [
    ("cron", "Cron"),
    ("interval", "Interval"),
]


class TaskResult(Model):
    """Persisted record of a task actor execution."""

    class Meta:
        table_name = "openviper_task_result"

    message_id = fields.UUIDField(unique=True)
    actor_name = fields.CharField(max_length=255)
    queue = fields.CharField(max_length=64, default="default")
    arguments = fields.JSONField(null=True)
    return_value = fields.JSONField(null=True)
    error_traceback = fields.TextField(null=True)
    status = fields.CharField(
        max_length=16,
        default="pending",
        choices=TASK_STATUS_CHOICES,
    )
    retries = fields.IntegerField(default=0)
    duration_ms = fields.BigIntegerField(null=True)
    created_at = fields.DateTimeField(auto_now_add=True)
    updated_at = fields.DateTimeField(auto_now=True)


class ScheduledJob(Model):
    """Maps periodic decorator config to database rows for distributed lock coordination."""

    class Meta:
        table_name = "openviper_scheduled_job"

    app = fields.CharField(max_length=128)
    name = fields.CharField(max_length=255, unique=True)
    schedule = fields.CharField(max_length=64)
    cron_description = fields.CharField(max_length=255, null=True)
    status = fields.CharField(max_length=32, default="active")
    last_enqueued_at = fields.DateTimeField(null=True)
    trigger_source = fields.CharField(
        max_length=32,
        choices=TRIGGER_SOURCE_CHOICES,
    )
