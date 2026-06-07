"""Logging utilities for OpenViper."""

from __future__ import annotations

import logging.config
import typing as t
from importlib import import_module
from types import ModuleType

uvicorn_config_module: ModuleType | None = None
uvicorn_available: bool = False

try:
    uvicorn_config_module = t.cast("ModuleType", import_module("uvicorn.config"))
    uvicorn_available = True
except ImportError:
    pass


def get_uvicorn_log_config() -> dict[str, object]:
    """Return a uvicorn logging configuration dict that includes timestamps."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "[%(asctime)s] %(levelprefix)s %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
                "use_colors": None,
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": (
                    "[%(asctime)s] %(levelprefix)s "
                    "%(client_addr)s - '%(request_line)s' %(status_code)s"
                ),
                "datefmt": "%Y-%m-%d %H:%M:%S",
                "use_colors": None,
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO"},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
        },
    }


# Automatically patch uvicorn in-place on import to support direct uvicorn execution
if uvicorn_available and uvicorn_config_module is not None:
    try:
        # Patch uvicorn's default config before any worker spawns.
        uvicorn_config_module.LOGGING_CONFIG = get_uvicorn_log_config()
        # Re-apply in case uvicorn already configured loggers at import time.
        logging.config.dictConfig(uvicorn_config_module.LOGGING_CONFIG)
    except Exception:
        pass
