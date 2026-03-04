"""Worker logging configuration for openviper tasks.

Sets up rotating file handlers in the project's ``logs/`` directory when
the task worker starts.  Two log files are maintained:

* ``logs/worker.log``       — all messages at the configured level (10 MB, 5 backups)
* ``logs/worker.error.log`` — WARNING and above only          (5 MB,  3 backups)

Log level and format are read from settings:

    TASKS = {
        "broker": "redis",
        "log_level": "INFO",     # optional — falls back to LOG_LEVEL
        "log_format": "text",    # optional — "text" (default) or "json"
        "log_dir": "/var/log/myapp",  # optional — defaults to {cwd}/logs
    }
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_LOGGING_CONFIGURED = False


def configure_worker_logging(
    log_dir: str | Path | None = None,
    log_level: str = "INFO",
    log_format: str = "text",
    log_to_file: bool = False,
) -> Path:
    """Set up file and console logging for the task worker.

    Safe to call multiple times — subsequent calls after the first are no-ops.

    Args:
        log_dir:     Directory for log files.  Defaults to ``{cwd}/logs``.
                     Ignored when *log_to_file* is ``False``.
        log_level:   Python logging level name (``"DEBUG"``, ``"INFO"``, …).
        log_format:  ``"text"`` (default) or ``"json"``.
        log_to_file: When ``False`` only the console (stdout) handler is
                     attached; no files are created.  Disable via
                     ``TASKS["log_to_file"] = False``.

    Returns:
        Resolved log directory path (directory is only created when
        *log_to_file* is ``True``).
    """
    global _LOGGING_CONFIGURED
    resolved = Path(log_dir) if log_dir else Path(os.getcwd()) / "logs"
    if _LOGGING_CONFIGURED:
        return resolved

    level = getattr(logging, log_level.upper(), logging.INFO)

    # ── Formatters ────────────────────────────────────────────────────────────
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

    # ── Build handler list ────────────────────────────────────────────────────
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

    # ── Attach to openviper.tasks and dramatiq loggers ────────────────────────
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


def configure_worker_logging_from_settings() -> Path:
    """Read openviper settings and call :func:`configure_worker_logging`.

    Reads ``TASKS.log_level``, ``TASKS.log_format``, ``TASKS.log_dir``,
    falling back to the top-level ``LOG_LEVEL`` / ``LOG_FORMAT`` settings.
    ``OPENVIPER_WORKER_LOG_LEVEL`` environment variable takes highest priority.
    """
    log_level = "INFO"
    log_format = "text"
    log_dir: str | None = None
    log_to_file: bool = False

    try:
        from openviper.conf import settings

        task_settings: dict[str, Any] = getattr(settings, "TASKS", {}) or {}
        log_level = task_settings.get(
            "log_level",
            task_settings.get("LOG_LEVEL", getattr(settings, "LOG_LEVEL", "INFO")),
        )
        log_format = task_settings.get(
            "log_format",
            task_settings.get("LOG_FORMAT", getattr(settings, "LOG_FORMAT", "text")),
        )
        log_dir = task_settings.get("log_dir") or task_settings.get("LOG_DIR")
        log_to_file = bool(task_settings.get("log_to_file", False))
    except Exception:
        pass

    # Env var takes highest priority — allows the runworker command to force
    # DEBUG level for --verbose without modifying settings.
    env_level = os.environ.get("OPENVIPER_WORKER_LOG_LEVEL")
    if env_level:
        log_level = env_level

    return configure_worker_logging(
        log_dir=log_dir,
        log_level=log_level,
        log_format=log_format,
        log_to_file=log_to_file,
    )
