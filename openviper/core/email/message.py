"""Email message construction helpers."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openviper.core.email.attachments import AttachmentData

_HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(slots=True)
class EmailMessageData:
    """Normalized email payload used by backends and queues."""

    recipients: list[str]
    subject: str
    text: str | None = None
    html: str | None = None
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    attachments: list[AttachmentData] = field(default_factory=list)
    sender: str = ""

    def delivery_recipients(self) -> list[str]:
        """Return all SMTP recipients including cc and bcc without duplicates."""
        recipients: list[str] = []
        seen: set[str] = set()
        for address in [*self.recipients, *self.cc, *self.bcc]:
            normalized = address.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                recipients.append(normalized)
        return recipients


def build_message(data: EmailMessageData) -> EmailMessage:
    """Construct a stdlib :class:`email.message.EmailMessage` instance."""
    message = EmailMessage()
    message["Subject"] = data.subject
    message["From"] = data.sender
    message["To"] = ", ".join(data.recipients)
    if data.cc:
        message["Cc"] = ", ".join(data.cc)

    plain_text = data.text
    if data.html and plain_text is None:
        plain_text = _html_to_text(data.html)

    if data.html is not None:
        message.set_content(plain_text or "")
        message.add_alternative(data.html, subtype="html")
    else:
        message.set_content(plain_text or "")

    for attachment in data.attachments:
        maintype, subtype = _split_mimetype(attachment.mimetype)
        message.add_attachment(
            attachment.content,
            maintype=maintype,
            subtype=subtype,
            filename=attachment.filename,
        )

    return message


def _html_to_text(value: str) -> str:
    stripped = _HTML_TAG_RE.sub(" ", value)
    return " ".join(html.unescape(stripped).split())


def _split_mimetype(mimetype: str) -> tuple[str, str]:
    if "/" not in mimetype:
        return "application", "octet-stream"
    maintype, subtype = mimetype.split("/", 1)
    return maintype, subtype
