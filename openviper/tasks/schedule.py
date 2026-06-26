"""Synchronise ``Registry.periodic_jobs`` with the ``ScheduledJob`` table.

On worker startup, creates or updates ``ScheduledJob`` rows for each
registered periodic job and deletes orphaned rows.
"""

from __future__ import annotations

from openviper.tasks.logging import get_task_logger
from openviper.tasks.models import ScheduledJob
from openviper.tasks.registry import Registry

try:
    from cron_descriptor import get_description as cron_get_description
except ImportError:
    cron_get_description = None

logger = get_task_logger("openviper.tasks.schedule")


def describe_cron(cron_expression: str) -> str | None:
    """Return a human-readable description of *cron_expression*.

    Returns ``None`` when ``cron_descriptor`` is not installed.
    """
    if cron_get_description is None:
        return None
    try:
        result: str | None = cron_get_description(cron_expression)
        return result
    except Exception:
        logger.warning("Failed to describe cron expression: %s", cron_expression, exc_info=True)
        return None


async def sync_scheduled_jobs() -> None:
    """Reconcile ``Registry.periodic_jobs`` with ``ScheduledJob`` rows.

    Creates or updates rows for registered jobs; deletes rows for
    jobs no longer in the registry.
    """
    registry = Registry()
    registered = registry.periodic_jobs

    try:
        existing_jobs = await ScheduledJob.objects.all()
    except Exception:
        logger.exception("Failed to query ScheduledJob table")
        return

    existing_by_name: dict[str, ScheduledJob] = {
        getattr(job, "name", ""): job for job in existing_jobs
    }

    for name, entry in registered.items():
        trigger = "cron" if entry.get("cron") else "interval"
        app_label = entry.get("app_label", "") or name.split(".")[0]
        schedule = entry.get("schedule", "")
        cron_description = describe_cron(schedule) if trigger == "cron" else None

        if name in existing_by_name:
            job = existing_by_name[name]
            try:
                if (
                    job.schedule != schedule
                    or job.trigger_source != trigger
                    or job.app != app_label
                    or job.status != "active"
                    or getattr(job, "cron_description", None) != cron_description
                ):
                    await ScheduledJob.objects.filter(id=job.id).update(
                        schedule=schedule,
                        trigger_source=trigger,
                        app=app_label,
                        status="active",
                        cron_description=cron_description,
                    )
                    logger.info("Updated ScheduledJob: %s", name)
            except Exception:
                logger.exception("Failed to update ScheduledJob: %s", name)
        else:
            try:
                await ScheduledJob.objects.create(
                    app=app_label,
                    name=name,
                    schedule=schedule,
                    status="active",
                    trigger_source=trigger,
                    cron_description=cron_description,
                )
                logger.info("Created ScheduledJob: %s", name)
            except Exception:
                logger.exception("Failed to create ScheduledJob: %s", name)

    for name, job in existing_by_name.items():
        if name not in registered:
            try:
                await ScheduledJob.objects.filter(id=job.id).delete()
                logger.info("Deleted ScheduledJob: %s", name)
            except Exception:
                logger.exception("Failed to delete ScheduledJob: %s", name)
