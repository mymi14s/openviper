"""OpenViper background task queue and periodic scheduler.

Provides a convention-over-configuration interface for defining
background actors and periodic jobs.  Developer modules never
import Dramatiq directly - the public API surface is:

* :func:`actor`  - declare a background task
* :func:`periodic` - declare a cron / interval job
"""

from __future__ import annotations

import typing as t

from openviper.tasks.decorators import actor, enqueue_task
from openviper.tasks.exceptions import (
    OpenViperTasksConfigurationError,
    OpenViperTasksError,
    ResultsBackendDisabledError,
)
from openviper.tasks.periodic import periodic
from openviper.tasks.registry import Registry
from openviper.tasks.types import TaskMessageProxy

__all__: list[str] = [
    "actor",
    "enqueue_task",
    "periodic",
    "Registry",
    "TaskMessageProxy",
    "OpenViperTasksError",
    "OpenViperTasksConfigurationError",
    "ResultsBackendDisabledError",
]
