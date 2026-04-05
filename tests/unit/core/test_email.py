"""Unit tests for the OpenViper core email module."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.core.email.backends import ConsoleBackend, SMTPBackend
from openviper.core.email.message import EmailMessageData, build_message
from openviper.core.email.sender import send_email


@pytest.fixture
def email_settings(tmp_path):
    """Patch email modules to use a simple in-memory settings object."""
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()

    stub = SimpleNamespace(
        EMAIL={
            "backend": "ConsoleBackend",
            "host": "localhost",
            "port": 2525,
            "use_tls": False,
            "use_ssl": False,
            "timeout": 10,
            "username": "",
            "user": "",
            "password": "",
            "from": "noreply@example.com",
            "default_sender": "noreply@example.com",
            "fail_silently": False,
            "use_background_worker": False,
        },
        TEMPLATES_DIR=str(templates_dir),
        INSTALLED_APPS=(),
        TASKS={"enabled": False, "broker": "stub"},
    )

    with (
        patch("openviper.core.email.sender.settings", stub),
        patch("openviper.core.email.backends.settings", stub),
        patch("openviper.core.email.templates.settings", stub),
        patch("openviper.core.email.queue.settings", stub),
    ):
        yield stub


class TestBuildMessage:
    """Test email message assembly."""

    def test_build_message_text_only(self):
        message = build_message(
            EmailMessageData(
                recipients=["to@example.com"],
                subject="Hello",
                text="Plain body",
                sender="noreply@example.com",
            )
        )

        assert message["To"] == "to@example.com"
        assert message["Subject"] == "Hello"
        assert "Plain body" in message.get_body(preferencelist=("plain",)).get_content()

    def test_build_message_html_omits_bcc_header(self):
        message = build_message(
            EmailMessageData(
                recipients=["to@example.com"],
                subject="HTML",
                text="Fallback",
                html="<h1>Hello</h1>",
                cc=["cc@example.com"],
                bcc=["bcc@example.com"],
                sender="noreply@example.com",
            )
        )

        assert message["Cc"] == "cc@example.com"
        assert message.get("Bcc") is None
        assert "<h1>Hello</h1>" in message.get_body(preferencelist=("html",)).get_content()


class TestSendEmail:
    """Test send_email behavior."""

    @pytest.mark.asyncio
    async def test_send_email_text_only(self, email_settings):
        with patch("openviper.core.email.sender._send_now", new_callable=AsyncMock) as mock_send:
            result = await send_email(
                recipients=["to@example.com"],
                subject="Welcome",
                text="Hello there",
            )

        assert result is True
        sent_data = mock_send.await_args.args[0]
        assert sent_data.text == "Hello there"
        assert sent_data.html is None

    @pytest.mark.asyncio
    async def test_send_email_html(self, email_settings):
        with patch("openviper.core.email.sender._send_now", new_callable=AsyncMock) as mock_send:
            await send_email(
                recipients=["to@example.com"],
                subject="HTML",
                html="<p>Hello</p>",
            )

        sent_data = mock_send.await_args.args[0]
        assert sent_data.html == "<p>Hello</p>"
        assert sent_data.text is None

    @pytest.mark.asyncio
    async def test_send_email_markdown(self, email_settings, tmp_path):
        template_path = Path(email_settings.TEMPLATES_DIR) / "welcome.md"
        template_path.write_text("# Hello {{ name }}\n\nWelcome aboard.", encoding="utf-8")

        with patch("openviper.core.email.sender._send_now", new_callable=AsyncMock) as mock_send:
            await send_email(
                recipients=["to@example.com"],
                subject="Markdown",
                template="welcome.md",
                context={"name": "Alice"},
            )

        sent_data = mock_send.await_args.args[0]
        assert sent_data.text is not None
        assert "Hello Alice" in sent_data.text
        assert sent_data.html is not None
        assert "<h1>" in sent_data.html

    @pytest.mark.asyncio
    async def test_send_email_jinja_template(self, email_settings):
        template_path = Path(email_settings.TEMPLATES_DIR) / "welcome.txt"
        template_path.write_text("Hello {{ name }}", encoding="utf-8")

        with patch("openviper.core.email.sender._send_now", new_callable=AsyncMock) as mock_send:
            await send_email(
                recipients=["to@example.com"],
                subject="Template",
                template="welcome.txt",
                context={"name": "Bob"},
            )

        sent_data = mock_send.await_args.args[0]
        assert sent_data.text == "Hello Bob"

    @pytest.mark.asyncio
    async def test_send_email_with_attachments(self, email_settings, tmp_path):
        report = tmp_path / "report.txt"
        report.write_text("report body", encoding="utf-8")

        with patch("openviper.core.email.sender._send_now", new_callable=AsyncMock) as mock_send:
            await send_email(
                recipients=["to@example.com"],
                subject="Attachments",
                text="See attached",
                attachments=[str(report), ("hello.txt", b"hello world", "text/plain")],
            )

        sent_data = mock_send.await_args.args[0]
        filenames = [attachment.filename for attachment in sent_data.attachments]
        assert filenames == ["report.txt", "hello.txt"]

    @pytest.mark.asyncio
    async def test_send_email_with_background_worker(self, email_settings):
        email_settings.EMAIL["use_background_worker"] = True
        email_settings.TASKS = {"enabled": True, "broker": "stub"}

        with (
            patch("openviper.core.email.sender.worker_available", return_value=True),
            patch(
                "openviper.core.email.sender.enqueue_email_job", new_callable=AsyncMock
            ) as mock_enqueue,
            patch("openviper.core.email.sender._send_now", new_callable=AsyncMock) as mock_send,
        ):
            result = await send_email(
                recipients=["to@example.com"],
                subject="Queued",
                text="Background",
            )

        assert result is True
        mock_enqueue.assert_awaited_once()
        mock_send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_email_background_falls_back_without_worker(self, email_settings):
        email_settings.EMAIL["use_background_worker"] = True
        email_settings.TASKS = {"enabled": False, "broker": "stub"}

        with (
            patch("openviper.core.email.sender.worker_available", return_value=False),
            patch(
                "openviper.core.email.sender.enqueue_email_job", new_callable=AsyncMock
            ) as mock_enqueue,
            patch("openviper.core.email.sender._send_now", new_callable=AsyncMock) as mock_send,
        ):
            result = await send_email(
                recipients=["to@example.com"],
                subject="Fallback",
                text="Send immediately",
            )

        assert result is True
        mock_enqueue.assert_not_awaited()
        mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_email_auto_detects_background_when_unset(self, email_settings):
        """When use_background_worker is absent, worker availability is auto-detected."""
        del email_settings.EMAIL["use_background_worker"]

        with (
            patch("openviper.core.email.sender.worker_available", return_value=True),
            patch(
                "openviper.core.email.sender.enqueue_email_job", new_callable=AsyncMock
            ) as mock_enqueue,
            patch("openviper.core.email.sender._send_now", new_callable=AsyncMock) as mock_send,
        ):
            result = await send_email(
                recipients=["to@example.com"],
                subject="Auto-detect",
                text="Worker detected",
            )

        assert result is True
        mock_enqueue.assert_awaited_once()
        mock_send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fail_silently_behavior(self, email_settings):
        with (
            patch(
                "openviper.core.email.sender._send_now",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            patch("openviper.core.email.sender.logger.exception") as mock_exception,
        ):
            result = await send_email(
                recipients=["to@example.com"],
                subject="Silent",
                text="Hello",
                fail_silently=True,
            )

        assert result is False
        mock_exception.assert_called_once()


class TestBackends:
    """Test email backend implementations."""

    @pytest.mark.asyncio
    async def test_console_backend(self, capsys):
        backend = ConsoleBackend()
        await backend.send(
            EmailMessageData(
                recipients=["to@example.com"],
                subject="Console",
                text="Hello console",
                sender="noreply@example.com",
            )
        )

        captured = capsys.readouterr()
        assert "Subject: Console" in captured.out
        assert "Hello console" in captured.out

    @pytest.mark.asyncio
    async def test_smtp_backend(self, email_settings):
        smtp_client = MagicMock()
        smtp_factory = MagicMock()
        smtp_factory.return_value.__enter__.return_value = smtp_client

        with patch("openviper.core.email.backends.smtplib.SMTP", smtp_factory):
            backend = SMTPBackend()
            await backend.send(
                EmailMessageData(
                    recipients=["to@example.com"],
                    cc=["cc@example.com"],
                    bcc=["bcc@example.com"],
                    subject="SMTP",
                    text="Hello smtp",
                    sender="noreply@example.com",
                )
            )

        smtp_client.send_message.assert_called_once()
        sent_recipients = smtp_client.send_message.call_args.kwargs["to_addrs"]
        assert sent_recipients == ["to@example.com", "cc@example.com", "bcc@example.com"]

    @pytest.mark.asyncio
    async def test_smtp_backend_resolves_sender_from_settings_when_empty(self, email_settings):
        """SMTPBackend fills in default_sender from settings when message has no sender."""
        email_settings.EMAIL["default_sender"] = "worker-configured@domain.com"
        smtp_client = MagicMock()
        smtp_factory = MagicMock()
        smtp_factory.return_value.__enter__.return_value = smtp_client

        with patch("openviper.core.email.backends.smtplib.SMTP", smtp_factory):
            backend = SMTPBackend()
            await backend.send(
                EmailMessageData(
                    recipients=["to@example.com"],
                    subject="No sender",
                    text="Body",
                    sender="",
                )
            )

        sent_message = smtp_client.send_message.call_args.args[0]
        assert sent_message["From"] == "worker-configured@domain.com"

    @pytest.mark.asyncio
    async def test_send_email_background_leaves_sender_empty_for_worker(self, email_settings):
        """send_email does not bake the default_sender into the payload for background jobs.

        The worker resolves the sender from its own settings at execution time.
        """
        email_settings.EMAIL["use_background_worker"] = True

        captured_data = {}

        async def capture_enqueue(data):
            captured_data["message"] = data

        with (
            patch("openviper.core.email.sender.worker_available", return_value=True),
            patch("openviper.core.email.sender.enqueue_email_job", side_effect=capture_enqueue),
        ):
            await send_email(
                recipients=["to@example.com"],
                subject="Background",
                text="Body",
            )

        assert captured_data["message"].sender == ""
