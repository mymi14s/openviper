"""Logging utilities for OpenViper."""

from __future__ import annotations

import logging.config
from types import ModuleType

_uvicorn_config: ModuleType | None = None
_uvicorn_available: bool = False

try:
    import uvicorn.config as _uvicorn_config_mod

    _uvicorn_config = _uvicorn_config_mod
    _uvicorn_available = True
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
if _uvicorn_available and _uvicorn_config is not None:
    try:
        # Update uvicorn's global default configuration
        _uvicorn_config.LOGGING_CONFIG = get_uvicorn_log_config()
        # Re-apply configuration in case uvicorn has already started configuring loggers
        logging.config.dictConfig(_uvicorn_config.LOGGING_CONFIG)
    except Exception:
        pass
