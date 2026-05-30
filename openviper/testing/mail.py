"""In-memory mail testing helpers."""

import dataclasses


@dataclasses.dataclass(frozen=True, slots=True)
class TestEmail:
    """Captured email record."""

    __test__ = False

    subject: str
    to: list[str]
    body: str = ""
    sender: str = ""


def assert_email_count(outbox: list[TestEmail], expected: int) -> None:
    actual = len(outbox)
    assert actual == expected, f"Expected {expected} email(s), got {actual}."


def assert_email_sent(outbox: list[TestEmail], recipient: str) -> None:
    assert any(
        recipient in email.to for email in outbox
    ), f"Expected email to recipient {recipient!r}."


def assert_email_subject(email: TestEmail, expected: str) -> None:
    assert email.subject == expected, f"Expected subject {expected!r}, got {email.subject!r}."


def assert_email_recipient(email: TestEmail, recipient: str) -> None:
    assert recipient in email.to, f"Expected recipient {recipient!r}, got {email.to!r}."


class InMemoryMailBackend:
    """Mail backend that captures messages in a caller-owned outbox."""

    def __init__(self, outbox: list[TestEmail]) -> None:
        self.outbox = outbox

    async def send(
        self,
        subject: str,
        to: list[str],
        body: str = "",
        sender: str = "",
    ) -> None:
        self.outbox.append(TestEmail(subject=subject, to=to, body=body, sender=sender))
