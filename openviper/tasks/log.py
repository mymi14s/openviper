"""Logging configuration for the openviper task worker and email subsystem.

Log files written to the project ``logs/`` directory (configurable via
``TASKS["log_dir"]`` or ``EMAIL["log_dir"]``):

* ``logs/worker.log``       — all messages at the configured level (10 MB, 5 backups)
* ``logs/worker.error.log`` — WARNING and above only (5 MB, 3 backups)
* ``logs/email.error.log``  — email WARNING and above (10 MB, 5 backups)
"""

from __future__ import annotations

import logging
import os
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

try:
    import openviper.conf as _conf_module
except Exception:
    _conf_module = None  # type: ignore[assignment]

_LOGGING_CONFIGURED = False
_LOGGING_LOCK = threading.Lock()


def configure_worker_logging(
    log_dir: str | Path | None = None,
    log_level: str = "INFO",
    log_format: str = "text",
    log_to_file: bool = False,
) -> Path:
    """Configure file and console handlers for the task worker loggers.

    Idempotent — subsequent calls after the first are no-ops.
    """
    global _LOGGING_CONFIGURED
    resolved = Path(log_dir) if log_dir else Path(os.getcwd()) / "logs"
    if _LOGGING_CONFIGURED:
        return resolved
    with _LOGGING_LOCK:
        if _LOGGING_CONFIGURED:
            return resolved

    level = getattr(logging, log_level.upper(), logging.INFO)

    if log_format == "json":
        file_fmt = (
            '{"time": "%(asctime)s", "level": "%(levelname)s",'
            ' "logger": "%(name)s", "message": %(message)r}'
        )
    else:
        file_fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    file_formatter = logging.Formatter(file_fmt, datefmt="%Y-%m-%d %H:%M:%S")
    console_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    handlers: list[logging.Handler] = []

    if log_to_file:
        resolved.mkdir(parents=True, exist_ok=True)

        worker_handler = RotatingFileHandler(
            resolved / "worker.log",
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        worker_handler.setLevel(level)
        worker_handler.setFormatter(file_formatter)

        error_handler = RotatingFileHandler(
            resolved / "worker.error.log",
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
            encoding="utf-8",
        )
        error_handler.setLevel(logging.WARNING)
        error_handler.setFormatter(file_formatter)

        handlers.extend([worker_handler, error_handler])

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(console_formatter)
    handlers.append(console_handler)

    for name in ("openviper.tasks", "dramatiq"):
        lg = logging.getLogger(name)
        lg.setLevel(level)
        present = {type(h) for h in lg.handlers}
        for h in handlers:
            if type(h) not in present:
                lg.addHandler(h)
                present.add(type(h))
        lg.propagate = False

    _LOGGING_CONFIGURED = True
    _lg = logging.getLogger("openviper.tasks")
    if log_to_file:
        _lg.info("Worker logging → %s  (level=%s, format=%s)", resolved, log_level, log_format)
    else:
        _lg.info("Worker logging → console only  (level=%s, log_to_file=False)", log_level)
    return resolved


_EMAIL_LOGGING_CONFIGURED = False
_EMAIL_LOGGING_LOCK = threading.Lock()


def configure_email_logging(
    log_dir: str | Path | None = None,
    log_format: str = "text",
) -> None:
    """Attach a rotating WARNING+ file handler to the ``openviper.email`` logger.

    Idempotent — subsequent calls after the first are no-ops.
    Writes to ``logs/email.error.log`` (10 MB, 5 backups).
    """
    global _EMAIL_LOGGING_CONFIGURED
    if _EMAIL_LOGGING_CONFIGURED:
        return
    with _EMAIL_LOGGING_LOCK:
        if _EMAIL_LOGGING_CONFIGURED:
            return

        resolved = Path(log_dir) if log_dir else Path(os.getcwd()) / "logs"
        resolved.mkdir(parents=True, exist_ok=True)

        if log_format == "json":
            fmt = (
                '{"time": "%(asctime)s", "level": "%(levelname)s",'
                ' "logger": "%(name)s", "message": %(message)r}'
            )
        else:
            fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

        formatter = logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")

        handler = RotatingFileHandler(
            resolved / "email.error.log",
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        handler.setLevel(logging.WARNING)
        handler.setFormatter(formatter)

        email_logger = logging.getLogger("openviper.email")
        existing_types = {type(h) for h in email_logger.handlers}
        if RotatingFileHandler not in existing_types:
            email_logger.addHandler(handler)

        _EMAIL_LOGGING_CONFIGURED = True


def configure_worker_logging_from_settings() -> Path:
    """Read project settings and call :func:`configure_worker_logging`."""
    log_level = "INFO"
    log_format = "text"
    log_dir: str | None = None
    log_to_file: bool = False

    try:
        _settings = getattr(_conf_module, "settings", None)
        task_settings: dict[str, Any] = getattr(_settings, "TASKS", {}) or {}
        log_level = task_settings.get(
            "log_level",
            task_settings.get("LOG_LEVEL", getattr(_settings, "LOG_LEVEL", "INFO")),
        )
        log_format = task_settings.get(
            "log_format",
            task_settings.get("LOG_FORMAT", getattr(_settings, "LOG_FORMAT", "text")),
        )
        log_dir = task_settings.get("log_dir") or task_settings.get("LOG_DIR")
        log_to_file = bool(task_settings.get("log_to_file", False))
    except Exception:
        pass

    env_level = os.environ.get("OPENVIPER_WORKER_LOG_LEVEL")
    if env_level:
        log_level = env_level

    return configure_worker_logging(
        log_dir=log_dir,
        log_level=log_level,
        log_format=log_format,
        log_to_file=log_to_file,
    )
