"""Public email sending API for OpenViper."""

from __future__ import annotations

import logging
import re
from typing import Any

from openviper.conf import settings
from openviper.core.email.attachments import resolve_attachments
from openviper.core.email.backends import EmailSettings, get_backend
from openviper.core.email.message import EmailMessageData
from openviper.core.email.templates import render_template_content

logger = logging.getLogger("openviper.email")

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def _read_email_config() -> dict[str, object]:
    config = getattr(settings, "EMAIL", {}) or {}
    return dict(config)


async def send_email(
    recipients: list[str] | str,
    subject: str,
    text: str | None = None,
    html: str | None = None,
    cc: list[str] | str | None = None,
    bcc: list[str] | str | None = None,
    attachments: list[Any] | None = None,
    template: str | None = None,
    context: dict[str, Any] | None = None,
    fail_silently: bool | None = None,
    background: bool | None = None,
    sender: str | None = None,
) -> bool:
    """Send an email immediately or enqueue it for background delivery."""
    email_config = _read_email_config()
    resolved_fail_silently = (
        bool(email_config.get("fail_silently", False)) if fail_silently is None else fail_silently
    )

    try:
        normalized_recipients = _normalize_addresses(recipients)
        normalized_cc = _normalize_addresses(cc)
        normalized_bcc = _normalize_addresses(bcc)

        if not normalized_recipients:
            raise ValueError("At least one recipient is required.")

        if template:
            rendered_text, rendered_html = render_template_content(template, context)
            if text is None:
                text = rendered_text
            if html is None:
                html = rendered_html

        resolved_attachments = await resolve_attachments(attachments)
        backend_settings = EmailSettings.from_settings()
        message_data = EmailMessageData(
            recipients=normalized_recipients,
            subject=subject,
            text=text,
            html=html,
            cc=normalized_cc,
            bcc=normalized_bcc,
            attachments=resolved_attachments,
            sender=sender or backend_settings.default_sender,
        )

        from openviper.core.email.queue import enqueue_email_job, worker_available

        worker_cfg = email_config.get("use_background_worker")  # None when key absent
        if background is not None:
            use_background = background
        elif worker_cfg is None:
            # Not explicitly configured — auto-detect availability (result is cached)
            use_background = worker_available()
        else:
            use_background = bool(worker_cfg)

        if use_background and worker_available():
            await enqueue_email_job(message_data)
            return True

        await _send_now(message_data)
        return True
    except Exception:
        if resolved_fail_silently:
            return False
        raise


async def _send_now(message_data: EmailMessageData) -> None:
    backend = get_backend()
    await backend.send(message_data)


def _normalize_addresses(values: list[str] | str | None) -> list[str]:
    if values is None:
        return []
    candidates = [values] if isinstance(values, str) else list(values)

    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        address = candidate.strip()
        if address and address not in seen:
            if _CONTROL_CHAR_RE.search(address):
                raise ValueError(f"Email address contains invalid control characters: {address!r}")
            seen.add(address)
            normalized.append(address)
    return normalized
