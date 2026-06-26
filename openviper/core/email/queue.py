"""Background queue integration for email delivery."""

from __future__ import annotations

import logging
from functools import lru_cache

from dramatiq.brokers.stub import StubBroker

from openviper.conf import settings  # noqa: F401 - kept for test patches on queue.settings
from openviper.core.email.attachments import attachment_from_payload, attachment_to_payload
from openviper.core.email.delivery import configure_email_log, send_now
from openviper.core.email.message import EmailMessageData
from openviper.tasks import actor
from openviper.tasks.broker import get_broker

logger = logging.getLogger("openviper.email")


@actor(queue_name="emails", actor_name="openviper.core.email.deliver_email")
async def deliver_email(payload: dict[str, object]) -> None:
    """Deserialise and deliver a queued email message.

    Enqueued by :func:`enqueue_email_job` when background delivery
    is active.  Runs on the ``emails`` queue inside a task worker.
    """
    configure_email_log()
    try:
        await send_now(payload_to_message(payload))
    except Exception:
        logger.exception(
            "Background email delivery failed: subject=%r recipients=%r",
            payload.get("subject"),
            payload.get("recipients"),
        )
        raise


async def enqueue_email_job(data: EmailMessageData) -> str | None:
    """Enqueue an email message for background delivery.

    When the task worker is available, the message is dispatched via
    the ``deliver_email`` actor.  Otherwise it falls back to direct
    synchronous delivery.
    """
    if worker_available():
        try:
            proxy = deliver_email.send(message_to_payload(data))
            return str(proxy.message_id)
        except Exception:
            logger.warning("Task enqueue failed, falling back to direct delivery")

    await deliver_email(message_to_payload(data))
    return None


@lru_cache(maxsize=1)
def worker_available() -> bool:
    """Return ``True`` when a Dramatiq task worker is reachable."""
    try:
        broker = get_broker()
        return not isinstance(broker, StubBroker)
    except Exception:
        return False


def message_to_payload(data: EmailMessageData) -> dict[str, object]:
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


def payload_string_list(value: object) -> list[str]:
    """Return string values from a list-like payload field."""
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def payload_to_message(payload: dict[str, object]) -> EmailMessageData:
    raw_attachments = payload.get("attachments", [])
    attachment_payloads = raw_attachments if isinstance(raw_attachments, list) else []
    attachments = [
        attachment_from_payload(
            {
                "filename": str(item.get("filename", "")),
                "content_b64": str(item.get("content_b64", "")),
                "mimetype": str(item.get("mimetype", "application/octet-stream")),
            }
        )
        for item in attachment_payloads
        if isinstance(item, dict)
    ]
    return EmailMessageData(
        recipients=payload_string_list(payload.get("recipients")),
        subject=str(payload.get("subject", "")),
        text=str(payload["text"]) if payload.get("text") is not None else None,
        html=str(payload["html"]) if payload.get("html") is not None else None,
        cc=payload_string_list(payload.get("cc")),
        bcc=payload_string_list(payload.get("bcc")),
        attachments=attachments,
        sender=str(payload.get("sender", "")),
    )
