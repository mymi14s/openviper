"""Background queue integration for email delivery."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from openviper.conf import settings  # noqa: F401 — kept for test patches on queue.settings
from openviper.core.email.attachments import attachment_from_payload, attachment_to_payload
from openviper.core.email.message import EmailMessageData
from openviper.tasks import task
from openviper.tasks.broker import get_broker


@task(queue_name="emails", actor_name="openviper.core.email.deliver_email")
async def _deliver_email_job(payload: dict[str, Any]) -> None:
    """Dramatiq actor — deserialises and delivers a queued email message."""
    # Local import avoids circular dependency (sender → queue → sender).
    from openviper.core.email.sender import _send_now

    await _send_now(_payload_to_message(payload))


async def enqueue_email_job(data: EmailMessageData) -> Any:
    """Queue an email delivery job for the background worker."""
    return _deliver_email_job.send(_message_to_payload(data))


@lru_cache(maxsize=1)
def worker_available() -> bool:
    """Return ``True`` when a real message-queue broker (Redis/RabbitMQ) is active.

    A StubBroker (used in tests) is never considered a real worker.
    Result is cached after the first call.
    """
    try:
        from dramatiq.brokers.stub import StubBroker

        return not isinstance(get_broker(), StubBroker)
    except Exception:
        return False


def _message_to_payload(data: EmailMessageData) -> dict[str, Any]:
    return {
        "recipients": list(data.recipients),
        "subject": data.subject,
        "text": data.text,
        "html": data.html,
        "cc": list(data.cc),
        "bcc": list(data.bcc),
        "sender": data.sender,
        "attachments": [attachment_to_payload(attachment) for attachment in data.attachments],
    }


def _payload_to_message(payload: dict[str, Any]) -> EmailMessageData:
    attachments = [attachment_from_payload(item) for item in payload.get("attachments", [])]
    return EmailMessageData(
        recipients=list(payload.get("recipients", [])),
        subject=str(payload.get("subject", "")),
        text=payload.get("text"),
        html=payload.get("html"),
        cc=list(payload.get("cc", [])),
        bcc=list(payload.get("bcc", [])),
        attachments=attachments,
        sender=str(payload.get("sender", "")),
    )
