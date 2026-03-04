"""ORM model for task result tracking.

The underlying table (``openviper_task_results``) is created automatically
by :mod:`openviper.tasks.results` on first use, so the framework migration
is optional.  Register it in ``INSTALLED_APPS`` if you want the admin panel
to display task results.

Column reference
----------------
See :mod:`openviper.tasks.results` for the full column reference.
"""

from __future__ import annotations

from openviper.db import fields
from openviper.db.models import Model


class TaskResult(Model):
    """Tracks the lifecycle of every background task message."""

    class Meta:
        table_name = "openviper_task_results"

    id = fields.IntegerField(primary_key=True, auto_increment=True)

    # ── Identity ──────────────────────────────────────────────────────────────
    message_id = fields.CharField(max_length=64, unique=True)
    actor_name = fields.CharField(max_length=255)
    queue_name = fields.CharField(max_length=100)

    # ── State ─────────────────────────────────────────────────────────────────
    # pending | running | success | failure | skipped | dead
    status = fields.CharField(max_length=20, default="pending")
    retries = fields.IntegerField(default=0)

    # ── Payload ───────────────────────────────────────────────────────────────
    args = fields.TextField(null=True)  # JSON-encoded list
    kwargs = fields.TextField(null=True)  # JSON-encoded dict

    # ── Outcome ───────────────────────────────────────────────────────────────
    result = fields.TextField(null=True)  # JSON-encoded return value
    error = fields.TextField(null=True)  # str(exception) on failure
    traceback = fields.TextField(null=True)  # full traceback on failure

    # ── Timestamps ────────────────────────────────────────────────────────────
    enqueued_at = fields.DateTimeField(null=True)
    started_at = fields.DateTimeField(null=True)
    completed_at = fields.DateTimeField(null=True)

    def __repr__(self) -> str:
        return (
            f"<TaskResult message_id={self.message_id!r}"
            f" actor={self.actor_name!r}"
            f" status={self.status!r}>"
        )

    @property
    def duration_ms(self) -> float | None:
        """Wall-clock execution time in milliseconds, or ``None`` if unknown."""
        if self.started_at and self.completed_at:
            delta = self.completed_at - self.started_at
            return delta.total_seconds() * 1000
        return None
