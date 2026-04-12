"""Additional unit tests for email queue/templates/backends.

These tests exercise small, previously-uncovered branches without invoking real
SMTP servers or message brokers.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.core.email import backends, queue, templates
from openviper.core.email.attachments import AttachmentData
from openviper.core.email.message import EmailMessageData


class TestTemplates:
    def test_invalid_template_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid template name"):
            templates.render_template_content("../secret.txt")

    def test_markdown_template_returns_text_and_html(self) -> None:
        fake_template = MagicMock()
        fake_template.render.return_value = "# Hello"
        env = MagicMock()
        env.get_template.return_value = fake_template

        with (
            patch(
                "openviper.core.email.templates._compute_template_search_paths", return_value=["x"]
            ),
            patch("openviper.core.email.templates.get_jinja2_env", return_value=env),
            patch("openviper.core.email.templates.markdown_lib", None),
        ):
            text, html = templates.render_template_content("welcome.md", context={"name": "a"})

        assert text == "# Hello"
        assert html is not None
        assert "<h1>" in html

    def test_html_template_returns_html_only(self) -> None:
        fake_template = MagicMock()
        fake_template.render.return_value = "<p>Hi</p>"
        env = MagicMock()
        env.get_template.return_value = fake_template

        with (
            patch(
                "openviper.core.email.templates._compute_template_search_paths", return_value=["x"]
            ),
            patch("openviper.core.email.templates.get_jinja2_env", return_value=env),
        ):
            text, html = templates.render_template_content("welcome.html")

        assert text is None
        assert html == "<p>Hi</p>"

    def test_plain_template_returns_text_only(self) -> None:
        fake_template = MagicMock()
        fake_template.render.return_value = "Hello"
        env = MagicMock()
        env.get_template.return_value = fake_template

        with (
            patch(
                "openviper.core.email.templates._compute_template_search_paths", return_value=["x"]
            ),
            patch("openviper.core.email.templates.get_jinja2_env", return_value=env),
        ):
            text, html = templates.render_template_content("welcome.txt")

        assert text == "Hello"
        assert html is None

    def test_render_markdown_uses_library_when_available(self) -> None:
        markdown_lib = MagicMock()
        markdown_lib.markdown.return_value = "<p>ok</p>"

        with patch("openviper.core.email.templates.markdown_lib", markdown_lib):
            rendered = templates.render_markdown("hello")

        assert rendered == "<p>ok</p>"


class TestQueue:
    def test_worker_available_cached(self) -> None:
        queue.worker_available.cache_clear()

        stub_mod = types.ModuleType("dramatiq.brokers.stub")

        class StubBroker:
            pass

        stub_mod.StubBroker = StubBroker

        with (
            patch.dict(sys.modules, {"dramatiq.brokers.stub": stub_mod}),
            patch("openviper.core.email.queue.get_broker", return_value=StubBroker()),
        ):
            assert queue.worker_available() is False
            # Cached value is reused.
            assert queue.worker_available() is False

    def test_worker_available_true_for_non_stub(self) -> None:
        queue.worker_available.cache_clear()

        stub_mod = types.ModuleType("dramatiq.brokers.stub")

        class StubBroker:
            pass

        stub_mod.StubBroker = StubBroker

        with (
            patch.dict(sys.modules, {"dramatiq.brokers.stub": stub_mod}),
            patch("openviper.core.email.queue.get_broker", return_value=object()),
        ):
            assert queue.worker_available() is True

    def test_worker_available_handles_errors(self) -> None:
        queue.worker_available.cache_clear()

        with patch("openviper.core.email.queue.get_broker", side_effect=RuntimeError("boom")):
            assert queue.worker_available() is False

    @pytest.mark.asyncio
    async def test_deliver_email_job_executes_send_now(self) -> None:
        sender_mod = types.ModuleType("openviper.core.email.sender")
        sender_mod._send_now = AsyncMock()
        sender_mod._configure_email_log = MagicMock()

        payload = {
            "recipients": ["to@example.com"],
            "subject": "Hi",
            "text": "Body",
            "html": None,
            "cc": [],
            "bcc": [],
            "sender": "from@example.com",
            "attachments": [],
        }

        with patch.dict(sys.modules, {"openviper.core.email.sender": sender_mod}):
            await queue._deliver_email_job.fn.__wrapped__(payload)

        sender_mod._send_now.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_enqueue_email_job_uses_actor_send(self) -> None:
        data = EmailMessageData(recipients=["to@example.com"], subject="Hi", text="Body")

        with patch.object(queue._deliver_email_job, "send", return_value="job") as mock_send:
            result = await queue.enqueue_email_job(data)

        assert result == "job"
        mock_send.assert_called_once()

    def test_payload_conversion_roundtrip_includes_attachments(self) -> None:
        msg = EmailMessageData(
            recipients=["to@example.com"],
            subject="Hi",
            text="Body",
            attachments=[AttachmentData(filename="a.txt", content=b"x", mimetype="text/plain")],
        )

        payload = queue._message_to_payload(msg)
        restored = queue._payload_to_message(payload)

        assert restored.recipients == ["to@example.com"]
        assert restored.attachments[0].filename == "a.txt"
        assert restored.attachments[0].content == b"x"


class TestBackends:
    def test_email_settings_from_settings_fallback_keys(self) -> None:
        stub = SimpleNamespace(
            EMAIL={
                "host": "smtp.example.com",
                "port": "587",
                "user": "u",
                "password": "p",
                "use_tls": True,
                "from": "from@example.com",
                "timeout": 5,
            }
        )

        with patch("openviper.core.email.backends.settings", stub):
            settings_obj = backends.EmailSettings.from_settings()

        assert settings_obj.username == "u"
        assert settings_obj.password == "p"
        assert settings_obj.default_sender == "from@example.com"
        assert settings_obj.use_tls is True

    def test_get_backend_unknown_raises(self) -> None:
        stub = SimpleNamespace(EMAIL={"backend": "unknown"})
        with patch("openviper.core.email.backends.settings", stub):
            with pytest.raises(ValueError, match="Unknown email backend"):
                backends.get_backend()

    def test_get_backend_aliases(self) -> None:
        stub = SimpleNamespace(EMAIL={"backend": "console"})
        with patch("openviper.core.email.backends.settings", stub):
            assert isinstance(backends.get_backend(), backends.ConsoleBackend)
            assert isinstance(backends.get_backend("smtp"), backends.SMTPBackend)

    @pytest.mark.asyncio
    async def test_console_backend_prints_message(self, capsys: pytest.CaptureFixture[str]) -> None:
        data = EmailMessageData(recipients=["to@example.com"], subject="Hi", text="Body")

        with patch("openviper.core.email.backends.build_message") as mock_build:
            mock_build.return_value = MagicMock(as_string=lambda: "MESSAGE")
            await backends.ConsoleBackend().send(data)

        out = capsys.readouterr().out
        assert "MESSAGE" in out

    @pytest.mark.asyncio
    async def test_smtp_backend_send_uses_to_thread(self) -> None:
        msg = MagicMock()
        data = EmailMessageData(
            recipients=["to@example.com"],
            subject="Hi",
            text="Body",
            cc=["cc@example.com"],
            bcc=["bcc@example.com"],
        )
        email_settings = backends.EmailSettings(
            host="smtp.example.com",
            port=25,
            username=None,
            password=None,
            use_tls=False,
            use_ssl=False,
            default_sender="from@example.com",
            timeout=10,
        )

        with (
            patch("openviper.core.email.backends.build_message", return_value=msg),
            patch(
                "openviper.core.email.backends.asyncio.to_thread", new_callable=AsyncMock
            ) as mock_to_thread,
        ):
            await backends.SMTPBackend(email_settings).send(data)

        mock_to_thread.assert_awaited_once()
        assert mock_to_thread.await_args.args[1] == msg
        assert set(mock_to_thread.await_args.args[2]) == {
            "to@example.com",
            "cc@example.com",
            "bcc@example.com",
        }

    def test_send_smtp_message_tls_and_login(self) -> None:
        client = MagicMock()
        ctx = MagicMock()
        ctx.__enter__.return_value = client
        ctx.__exit__.return_value = None

        email_settings = backends.EmailSettings(
            host="smtp.example.com",
            port=25,
            username="user",
            password="pass",
            use_tls=True,
            use_ssl=False,
            default_sender="from@example.com",
            timeout=10,
        )

        with patch("openviper.core.email.backends.smtplib.SMTP", return_value=ctx) as mock_smtp:
            backends._send_smtp_message(MagicMock(), ["to@example.com"], email_settings)

        mock_smtp.assert_called_once_with("smtp.example.com", 25, timeout=10)
        client.starttls.assert_called_once()
        client.login.assert_called_once_with("user", "pass")
        client.send_message.assert_called_once()

    def test_send_smtp_message_ssl_uses_smtp_ssl_class(self) -> None:
        client = MagicMock()
        ctx = MagicMock()
        ctx.__enter__.return_value = client
        ctx.__exit__.return_value = None

        email_settings = backends.EmailSettings(
            host="smtp.example.com",
            port=465,
            username=None,
            password=None,
            use_tls=True,
            use_ssl=True,
            default_sender="from@example.com",
            timeout=10,
        )

        with patch("openviper.core.email.backends.smtplib.SMTP_SSL", return_value=ctx) as mock_ssl:
            backends._send_smtp_message(MagicMock(), ["to@example.com"], email_settings)

        mock_ssl.assert_called_once_with("smtp.example.com", 465, timeout=10)
        client.starttls.assert_not_called()
