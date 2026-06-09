"""Read-only task status and schedule inspection endpoints."""

from __future__ import annotations

import typing as t

from openviper.http.response import JSONResponse
from openviper.tasks.registry import Registry

if t.TYPE_CHECKING:
    from openviper.http.request import Request


async def task_status(request: Request) -> JSONResponse:
    """Return a summary of registered actors and periodic jobs."""
    registry = Registry()
    return JSONResponse(
        {
            "actors": list(registry.actors.keys()),
            "periodic_jobs": list(registry.periodic_jobs.keys()),
        }
    )


async def scheduled_jobs(request: Request) -> JSONResponse:
    """Return the list of scheduled periodic jobs."""
    registry = Registry()
    return JSONResponse(
        {
            "jobs": [
                {
                    "name": entry["name"],
                    "schedule": entry["schedule"],
                    "cron": entry.get("cron"),
                    "every": entry.get("every"),
                }
                for entry in registry.periodic_jobs.values()
            ]
        }
    )
