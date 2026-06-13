"""Shared email delivery helpers."""

from __future__ import annotations

import logging
import os
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING

from openviper.core.email.backends import get_backend, read_email_config

if TYPE_CHECKING:
    from openviper.core.email.message import EmailMessageData

logger = logging.getLogger("openviper.email")

EMAIL_LOGGING_CONFIGURED = False
EMAIL_LOGGING_LOCK = threading.Lock()


def configure_email_log() -> None:
    """Initialise email file logging from project settings."""
    global EMAIL_LOGGING_CONFIGURED
    if EMAIL_LOGGING_CONFIGURED:
        return
    with EMAIL_LOGGING_LOCK:
        if EMAIL_LOGGING_CONFIGURED:
            return
        try:
            email_cfg = read_email_config()
            raw_dir = email_cfg.get("log_dir")
            log_dir: str | Path | None = str(raw_dir) if raw_dir is not None else None
            log_format = str(email_cfg.get("log_format") or "text")

            resolved = Path(log_dir) if log_dir else Path(os.getcwd()) / "logs"
            resolved.mkdir(parents=True, exist_ok=True)

            if log_format == "json":
                fmt = (
                    '{"time": "%(asctime)s", "level": "%(levelname)s",'
                    ' "logger": "%(name)s", "message": %(message)s}'
                )
            else:
                fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

            formatter = logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")

            handler = RotatingFileHandler(
                resolved / "email.error.log",
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            handler.setLevel(logging.WARNING)
            handler.setFormatter(formatter)

            email_logger = logging.getLogger("openviper.email")
            existing_types = {type(h) for h in email_logger.handlers}
            if RotatingFileHandler not in existing_types:
                email_logger.addHandler(handler)

            EMAIL_LOGGING_CONFIGURED = True
        except Exception:
            logger.debug("Email log configuration failed", exc_info=True)


async def send_now(message_data: EmailMessageData) -> None:
    """Send a normalized email payload through the configured backend."""
    backend = get_backend()
    await backend.send(message_data)
