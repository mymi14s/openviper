"""Stale task result cleanup."""

from __future__ import annotations

import datetime

from openviper.tasks.logging import get_task_logger
from openviper.tasks.models import TaskResult
from openviper.utils import timezone

logger = get_task_logger("openviper.tasks.cleanup")


async def cleanup_stale_results(max_age_hours: int = 168) -> int:
    """Delete ``TaskResult`` rows older than *max_age_hours*. Returns count."""
    cutoff = timezone.now() - datetime.timedelta(hours=max_age_hours)
    count = await TaskResult.objects.filter(
        created_at__lt=cutoff,
    ).delete()
    logger.info("Cleaned up %d stale task results", count)
    return count
