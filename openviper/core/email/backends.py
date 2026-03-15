"""Email backends for OpenViper."""

from __future__ import annotations

import asyncio
import smtplib
from dataclasses import dataclass
from typing import Protocol

from openviper.conf import settings
from openviper.core.email.message import EmailMessageData, build_message


def _read_email_config() -> dict[str, object]:
    config = getattr(settings, "EMAIL", {}) or {}
    return dict(config)


@dataclass(slots=True)
class EmailSettings:
    """SMTP and email behavior settings."""

    host: str
    port: int
    username: str | None
    password: str | None
    use_tls: bool
    use_ssl: bool
    default_sender: str
    timeout: int

    @classmethod
    def from_settings(cls) -> EmailSettings:
        config = _read_email_config()
        username = str(config.get("username") or config.get("user") or "")
        password_value = config.get("password") or None
        sender = str(config.get("default_sender") or config.get("from") or "noreply@example.com")
        return cls(
            host=str(config.get("host") or "localhost"),
            port=int(config.get("port") or 25),  # type: ignore[call-overload]
            username=username or None,
            password=str(password_value) if password_value is not None else None,
            use_tls=bool(config.get("use_tls", False)),
            use_ssl=bool(config.get("use_ssl", False)),
            default_sender=sender,
            timeout=int(config.get("timeout") or 10),  # type: ignore[call-overload]
        )


class EmailBackend(Protocol):
    """Minimal protocol for email backend implementations."""

    async def send(self, data: EmailMessageData) -> None:
        """Send a normalized email payload."""


class ConsoleBackend:
    """Development backend that prints rendered email content to stdout."""

    async def send(self, data: EmailMessageData) -> None:
        message = build_message(data)
        print("=" * 72)
        print(message.as_string())
        print("=" * 72)


class SMTPBackend:
    """SMTP delivery backend."""

    def __init__(self, email_settings: EmailSettings | None = None) -> None:
        self.email_settings = email_settings or EmailSettings.from_settings()

    async def send(self, data: EmailMessageData) -> None:
        message = build_message(data)
        recipients = data.delivery_recipients()
        await asyncio.to_thread(_send_smtp_message, message, recipients, self.email_settings)


def get_backend(name: str | None = None) -> EmailBackend:
    """Return an email backend instance from framework settings or an explicit name."""
    config = _read_email_config()
    resolved = str(name or config.get("backend") or "SMTPBackend").lower()
    mapping = {
        "console": ConsoleBackend,
        "consolebackend": ConsoleBackend,
        "smtp": SMTPBackend,
        "smtpbackend": SMTPBackend,
    }
    backend_class = mapping.get(resolved)
    if backend_class is None:
        raise ValueError(f"Unknown email backend: {name or config.get('backend', '')!r}")
    return backend_class()


async def send_smtp(data: EmailMessageData) -> None:
    """Send an email via the configured SMTP backend."""
    await SMTPBackend().send(data)


async def send_console(data: EmailMessageData) -> None:
    """Send an email via the console backend."""
    await ConsoleBackend().send(data)


def _send_smtp_message(message, recipients: list[str], email_settings: EmailSettings) -> None:
    smtp_cls = smtplib.SMTP_SSL if email_settings.use_ssl else smtplib.SMTP
    with smtp_cls(
        email_settings.host, email_settings.port, timeout=email_settings.timeout
    ) as client:
        if email_settings.use_tls and not email_settings.use_ssl:
            client.starttls()
        if email_settings.username:
            client.login(email_settings.username, email_settings.password or "")
        client.send_message(message, to_addrs=recipients)
