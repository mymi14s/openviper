"""Async email utilities for OpenViper.

The public entry-point is :func:`send_email`, which supports immediate or
background delivery, Jinja2 templates, Markdown-to-HTML rendering, attachments,
and pluggable delivery backends.
"""

from openviper.core.email.attachments import AttachmentData
from openviper.core.email.backends import (
    ConsoleBackend,
    EmailSettings,
    SMTPBackend,
    get_backend,
    send_console,
    send_smtp,
)
from openviper.core.email.message import EmailMessageData, build_message
from openviper.core.email.queue import enqueue_email_job, worker_available
from openviper.core.email.sender import send_email

__all__ = [
    "AttachmentData",
    "ConsoleBackend",
    "EmailMessageData",
    "EmailSettings",
    "SMTPBackend",
    "build_message",
    "enqueue_email_job",
    "get_backend",
    "send_console",
    "send_email",
    "send_smtp",
    "worker_available",
]
