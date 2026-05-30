"""Shared email delivery helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from openviper.conf import settings
from openviper.core.email.backends import get_backend, read_email_config
from openviper.tasks.log import configure_email_logging

if TYPE_CHECKING:
    from openviper.core.email.message import EmailMessageData

logger = logging.getLogger("openviper.email")


def configure_email_log() -> None:
    """Initialise email file logging from project settings."""
    try:
        email_cfg = read_email_config()
        task_cfg: dict[str, object] = dict(getattr(settings, "TASKS", {}) or {})
        raw_dir = email_cfg.get("log_dir") or task_cfg.get("log_dir") or task_cfg.get("LOG_DIR")
        log_dir: str | None = str(raw_dir) if raw_dir is not None else None
        log_format = str(email_cfg.get("log_format") or task_cfg.get("log_format") or "text")
        configure_email_logging(log_dir=log_dir, log_format=log_format)
    except Exception:
        logger.debug("Email log configuration failed", exc_info=True)


async def send_now(message_data: EmailMessageData) -> None:
    """Send a normalized email payload through the configured backend."""
    backend = get_backend()
    await backend.send(message_data)
