"""Unit tests for remaining branches in :mod:`openviper.core.email.message`."""

from __future__ import annotations

from openviper.core.email.attachments import AttachmentData
from openviper.core.email.message import EmailMessageData, _split_mimetype, build_message


def test_delivery_recipients_deduplicates_and_strips() -> None:
    data = EmailMessageData(
        recipients=[" to@example.com ", "to@example.com"],
        subject="Hi",
        cc=["cc@example.com", ""],
        bcc=["bcc@example.com", "cc@example.com"],
    )

    assert data.delivery_recipients() == ["to@example.com", "cc@example.com", "bcc@example.com"]


def test_build_message_html_generates_plain_text_fallback() -> None:
    data = EmailMessageData(
        recipients=["to@example.com"],
        subject="Hi",
        html="<h1>Hello</h1><p>World</p>",
        attachments=[AttachmentData(filename="a.bin", content=b"x")],
        sender="from@example.com",
    )

    message = build_message(data)
    assert message.get_body(preferencelist=("plain",)).get_content().strip() == "Hello World"
    assert (
        message.get_body(preferencelist=("html",)).get_content().strip()
        == "<h1>Hello</h1><p>World</p>"
    )


def test_split_mimetype_falls_back_when_missing_subtype() -> None:
    assert _split_mimetype("text/plain") == ("text", "plain")
    assert _split_mimetype("invalid") == ("application", "octet-stream")
