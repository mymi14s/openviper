"""Task subsystem logging.

Provides :func:`get_task_logger` for named log channels and
:func:`configure_task_logging` for file-based log rotation.

Task loggers are rooted under ``openviper.tasks`` with
``propagate=False`` to prevent worker output from leaking into
the web-server process. In worker mode, propagation is enabled
so records reach the root logger and its file handler.
"""

from __future__ import annotations

import logging
import threading
import typing as t
from pathlib import Path

from openviper.conf.settings import OVDefaultHandler
from openviper.utils.logging import ConcurrentRotatingFileHandler, build_formatter

TASK_LOGGING_CONFIGURED = False
TASK_LOGGING_LOCK = threading.Lock()

TASK_LOGGER_NAMES: set[str] = set()

WORKER_MODE: bool = False


def get_task_logger(name: str) -> logging.Logger:
    """Return a logger under the ``openviper.tasks`` hierarchy."""
    logger = logging.getLogger(name)
    logger.propagate = WORKER_MODE
    TASK_LOGGER_NAMES.add(name)
    return logger


def configure_task_logging(
    cfg: dict[str, t.Any],
    *,
    worker_mode: bool = False,
) -> None:
    """Initialise file-based task logging from *cfg* (``settings.TASKS``).

    Creates a :class:`ConcurrentRotatingFileHandler` and attaches it
    to the task logger hierarchy. When *worker_mode* is ``True``,
    the handler is attached to the root logger and task loggers
    propagate upward.
    """
    global TASK_LOGGING_CONFIGURED, WORKER_MODE
    if TASK_LOGGING_CONFIGURED:
        return

    with TASK_LOGGING_LOCK:
        if TASK_LOGGING_CONFIGURED:
            return

        log_cfg = cfg.get("logging", {})
        if not isinstance(log_cfg, dict):
            log_cfg = {}

        file_cfg = log_cfg.get("file")
        if not file_cfg:
            if worker_mode:
                WORKER_MODE = True
                root_task_logger = logging.getLogger("openviper.tasks")
                root_task_logger.propagate = True
                for name in TASK_LOGGER_NAMES:
                    logging.getLogger(name).propagate = True
                ov_logger = logging.getLogger("openviper")
                ov_logger.handlers = [
                    h for h in ov_logger.handlers if not isinstance(h, OVDefaultHandler)
                ]
                root_logger = logging.getLogger()
                root_logger.addHandler(logging.NullHandler())
            TASK_LOGGING_CONFIGURED = True
            return

        if isinstance(file_cfg, dict):
            log_dir = str(file_cfg.get("log_dir", "logs"))
            file_name = str(file_cfg.get("file_name", "tasks.log"))
            max_size_mb = float(file_cfg.get("max_size", 10))
            max_bytes = int(max_size_mb * 1024 * 1024)
            log_format = str(file_cfg.get("log_format", "json"))
        else:
            log_dir = "logs"
            file_name = "tasks.log"
            max_bytes = 10 * 1024 * 1024
            log_format = "json"

        resolved = Path(log_dir)
        resolved.mkdir(parents=True, exist_ok=True)
        log_path = resolved / file_name

        formatter = build_formatter(log_format, console=False)

        handler = ConcurrentRotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(formatter)

        task_level = getattr(logging, str(log_cfg.get("level", "INFO")).upper(), logging.INFO)

        root_task_logger = logging.getLogger("openviper.tasks")
        root_task_logger.setLevel(task_level)

        if worker_mode:
            WORKER_MODE = True

            root_task_logger.propagate = True

            root_logger = logging.getLogger()
            root_logger.addHandler(handler)
            root_logger.setLevel(task_level)

            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(build_formatter(log_format, console=True))
            root_logger.addHandler(console_handler)

            ov_logger = logging.getLogger("openviper")
            ov_logger.handlers = [
                h for h in ov_logger.handlers if not isinstance(h, OVDefaultHandler)
            ]
            if ov_logger.level > task_level or ov_logger.level == 0:
                ov_logger.setLevel(task_level)

            for name in TASK_LOGGER_NAMES:
                logging.getLogger(name).propagate = True
        else:
            root_task_logger.addHandler(handler)
            root_task_logger.propagate = False

        TASK_LOGGING_CONFIGURED = True
