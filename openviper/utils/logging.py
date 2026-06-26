"""Logging utilities for OpenViper."""

from __future__ import annotations

import logging
import logging.config
import typing as t
from importlib import import_module
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import ModuleType

uvicorn_config_module: ModuleType | None = None
uvicorn_available: bool = False

try:
    uvicorn_config_module = t.cast("ModuleType", import_module("uvicorn.config"))
    uvicorn_available = True
except ImportError:
    pass


CONSOLE_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
CONSOLE_DATE_FORMAT = "%H:%M:%S"
FILE_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
FILE_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
UVICORN_FORMAT = "[%(asctime)s] %(levelprefix)s %(message)s"
UVICORN_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def build_formatter(
    log_format: str = "text",
    *,
    console: bool = False,
) -> logging.Formatter:
    """Create a logging formatter aligned with OpenViper's log style.

    Args:
        log_format: ``"text"`` for human-readable or ``"json"`` for structured.
        console: When ``True``, use the shorter time-only date format suitable
                 for terminal output.  When ``False``, include the full date.
    """
    if log_format == "json":
        fmt = (
            '{"time": "[%(asctime)s]", "level": "%(levelname)s",'
            ' "logger": "%(name)s", "message": %(message)s}'
        )
        datefmt = FILE_DATE_FORMAT
    elif console:
        fmt = CONSOLE_FORMAT
        datefmt = CONSOLE_DATE_FORMAT
    else:
        fmt = FILE_FORMAT
        datefmt = FILE_DATE_FORMAT
    return logging.Formatter(fmt, datefmt=datefmt)


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


if uvicorn_available and uvicorn_config_module is not None:
    try:
        uvicorn_config_module.LOGGING_CONFIG = get_uvicorn_log_config()
        logging.config.dictConfig(uvicorn_config_module.LOGGING_CONFIG)
    except Exception:
        logging.getLogger("openviper").warning("Failed to apply Uvicorn log config", exc_info=True)


class ConcurrentRotatingFileHandler(RotatingFileHandler):
    """Thread-safe rotating file handler with process-safe file locking.

    Extends :class:`logging.handlers.RotatingFileHandler` with advisory
    file locking so that concurrent writers (multiple worker processes)
    do not interleave partial lines during rotation.

    Rotation is bounded strictly by the ``maxBytes`` configuration.
    When the current log file reaches ``maxBytes``, it is rotated to
    ``<filename>.1``, ``<filename>.2``, etc., up to ``backupCount``
    archived files.
    """

    def __init__(
        self,
        filename: str | Path,
        mode: str = "a",
        maxBytes: int = 0,  # noqa: N803
        backupCount: int = 5,  # noqa: N803
        encoding: str | None = None,
        delay: bool = False,
    ) -> None:
        if isinstance(filename, Path):
            filename = str(filename)
        super().__init__(
            filename,
            mode=mode,
            maxBytes=maxBytes,
            backupCount=backupCount,
            encoding=encoding,
            delay=delay,
        )

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a record with exclusive file access during rotation."""
        try:
            if self.shouldRollover(record):
                self.doRollover()
        except Exception:
            self.handleError(record)
            return
        super().emit(record)
