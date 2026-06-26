"""Public email sending API for OpenViper."""

from __future__ import annotations

import logging
import re

from openviper.core.email.attachments import resolve_attachments
from openviper.core.email.backends import read_email_config
from openviper.core.email.delivery import configure_email_log, send_now
from openviper.core.email.message import EmailMessageData
from openviper.core.email.queue import enqueue_email_job, worker_available
from openviper.core.email.templates import render_template_content

logger = logging.getLogger("openviper.email")

CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


async def send_email(
    recipients: list[str] | str,
    subject: str,
    text: str | None = None,
    html: str | None = None,
    cc: list[str] | str | None = None,
    bcc: list[str] | str | None = None,
    attachments: list[object] | None = None,
    template: str | None = None,
    context: dict[str, object] | None = None,
    fail_silently: bool | None = None,
    background: bool | None = None,
    sender: str | None = None,
) -> bool:
    """Send an email immediately or enqueue it for background delivery."""
    email_config = read_email_config()
    resolved_fail_silently = (
        bool(email_config.get("fail_silently", False)) if fail_silently is None else fail_silently
    )

    try:
        normalized_recipients = normalize_addresses(recipients)
        normalized_cc = normalize_addresses(cc)
        normalized_bcc = normalize_addresses(bcc)

        if not normalized_recipients:
            raise ValueError("At least one recipient is required.")

        if template:
            rendered_text, rendered_html = render_template_content(template, context)
            if text is None:
                text = rendered_text
            if html is None:
                html = rendered_html

        resolved_attachments = await resolve_attachments(attachments)
        message_data = EmailMessageData(
            recipients=normalized_recipients,
            subject=subject,
            text=text,
            html=html,
            cc=normalized_cc,
            bcc=normalized_bcc,
            attachments=resolved_attachments,
            sender=sender or "",
        )

        resolved_background = background
        if resolved_background is None:
            cfg_background = email_config.get("background")
            if cfg_background is not None:
                resolved_background = bool(cfg_background)

        use_background = resolved_background is True or (
            resolved_background is None and worker_available()
        )

        if use_background and worker_available():
            try:
                await enqueue_email_job(message_data)
                return True
            except Exception:
                if resolved_background is True:
                    raise
                logger.warning(
                    "Background email enqueue failed; sending inline.",
                    exc_info=True,
                )

        await send_now(message_data)
        return True
    except Exception:
        configure_email_log()
        logger.exception("Email delivery failed: subject=%r", subject)
        if resolved_fail_silently:
            return False
        raise


def normalize_addresses(values: list[str] | str | None) -> list[str]:
    if values is None:
        return []
    candidates = [values] if isinstance(values, str) else list(values)

    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        address = candidate.strip()
        if address and address not in seen:
            if CONTROL_CHAR_RE.search(address):
                raise ValueError(f"Email address contains invalid control characters: {address!r}")
            seen.add(address)
            normalized.append(address)
    return normalized
