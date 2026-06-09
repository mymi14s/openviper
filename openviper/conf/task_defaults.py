"""Task subsystem default configuration values.

Standalone module with zero intra-framework imports to avoid circular
dependencies when referenced from ``openviper.conf.settings``.
"""

from __future__ import annotations

import typing as t

DEFAULT_TASKS: dict[str, t.Any] = {
    "enabled": 1,
    "broker": "redis",
    "broker_url": "",
    "backend_url": "",
    "logging": {
        "level": "INFO",
        "file": None,
        "database": None,
    },
}
