"""Shared fixtures and helpers for security unit tests."""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

from openviper.conf import settings as settings_mod

# ---------------------------------------------------------------------------
# ASGI scope / request helpers
# ---------------------------------------------------------------------------


def make_scope(
    method: str = "GET",
    path: str = "/",
    query_string: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
    scheme: str = "http",
    server: tuple[str, int] | None = ("localhost", 8000),
    path_params: dict | None = None,
    body: bytes = b"",
) -> dict[str, object]:
    """Build a minimal ASGI HTTP scope dict for testing."""
    return {
        "type": "http",
        "method": method.upper(),
        "path": path,
        "query_string": query_string,
        "headers": headers or [],
        "scheme": scheme,
        "server": server,
        "root_path": "",
        "path_params": path_params or {},
        "body": body,
    }


async def noop_receive() -> dict[str, object]:
    """ASGI receive callable that returns an empty body."""
    return {"type": "http.request", "body": b"", "more_body": False}


class BodyReceive:
    """ASGI receive callable that yields a pre-set body."""

    def __init__(self, body: bytes) -> None:
        self._body = body
        self._sent = False

    async def __call__(self) -> dict[str, object]:
        if self._sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        self._sent = True
        return {"type": "http.request", "body": self._body, "more_body": False}


class SendCollector:
    """ASGI send callable that collects all messages for inspection."""

    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def __call__(self, message: dict[str, object]) -> None:
        self.messages.append(message)

    @property
    def started(self) -> dict[str, object] | None:
        """Return the first http.response.start message, or None."""
        for msg in self.messages:
            if msg.get("type") == "http.response.start":
                return msg
        return None

    @property
    def status_code(self) -> int | None:
        started = self.started
        if started:
            return started.get("status")
        return None

    @property
    def headers_dict(self) -> dict[str, str]:
        """Return response headers as a lowercase-keyed dict."""
        started = self.started
        if not started:
            return {}
        return {
            name.decode("latin-1").lower(): value.decode("latin-1")
            for name, value in started.get("headers", [])
        }

    @property
    def body(self) -> bytes:
        """Return the concatenated response body."""
        chunks = []
        for msg in self.messages:
            if msg.get("type") == "http.response.body":
                chunks.append(msg.get("body", b""))
        return b"".join(chunks)


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def override_settings(**overrides: object):
    """Temporarily override settings attributes for testing.

    Uses object.__setattr__ to bypass the frozen dataclass restriction,
    then restores original values on exit.
    """
    settings = settings_mod

    saved: dict[str, object] = {}
    for key, value in overrides.items():
        instance = object.__getattribute__(settings, "_instance")
        if instance is not None:
            saved[key] = getattr(instance, key, MISSING)
            object.__setattr__(instance, key, value)
        else:
            saved[key] = MISSING
    try:
        yield settings
    finally:
        for key, value in saved.items():
            instance = object.__getattribute__(settings, "_instance")
            if instance is not None:
                if value is MISSING:
                    # Can't delete from frozen dataclass; restore default
                    pass
                else:
                    object.__setattr__(instance, key, value)


MISSING = object()


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def assert_rejected(status_code: int, *, min_code: int = 400, max_code: int = 499) -> None:
    """Assert that a status code represents a security rejection (4xx)."""
    assert (
        min_code <= status_code <= max_code
    ), f"Expected rejection ({min_code}-{max_code}), got {status_code}"


def assert_no_sensitive_data(
    data: str,
    sensitive_keys: tuple[str, ...] = (
        "password",
        "secret",
        "token",
        "api_key",
        "private_key",
        "authorization",
        "cookie",
        "database_url",
    ),
) -> None:
    """Assert that no sensitive key names appear as literal substrings in data.

    This checks for accidental exposure of sensitive field names in
    serialized output, logs, or error messages.
    """
    lower = data.lower()
    for key in sensitive_keys:
        assert key not in lower, f"Sensitive key {key!r} found in output"


def assert_header_value(headers: dict[str, str], name: str, expected: str) -> None:
    """Assert that a header has exactly the expected value."""
    assert name in headers, f"Header {name!r} not found in {headers}"
    assert (
        headers[name] == expected
    ), f"Expected header {name!r}={expected!r}, got {headers[name]!r}"


def assert_header_contains(headers: dict[str, str], name: str, substring: str) -> None:
    """Assert that a header value contains the given substring."""
    assert name in headers, f"Header {name!r} not found in {headers}"
    assert (
        substring in headers[name]
    ), f"Expected {name!r} to contain {substring!r}, got {headers[name]!r}"


def assert_header_absent(headers: dict[str, str], name: str) -> None:
    """Assert that a header is absent from the response."""
    assert name not in headers, f"Header {name!r} should not be present, got {headers[name]!r}"


# ---------------------------------------------------------------------------
# Async test helpers
# ---------------------------------------------------------------------------


def run_concurrently(*coros):
    """Run multiple coroutines concurrently and return their results."""

    async def _run():
        tasks = [asyncio.ensure_future(c) for c in coros]
        return await asyncio.gather(*tasks)

    return asyncio.get_event_loop().run_until_complete(_run())


class MockUser:
    """A mock user object for testing authentication and authorization."""

    def __init__(
        self,
        user_id: int = 1,
        username: str = "testuser",
        is_authenticated: bool = True,
        is_active: bool = True,
        is_staff: bool = False,
        is_superuser: bool = False,
        roles: list[str] | None = None,
        permissions: list[str] | None = None,
        tenant_id: str | None = None,
    ) -> None:
        self.id = user_id
        self.pk = user_id
        self.username = username
        self.is_authenticated = is_authenticated
        self.is_active = is_active
        self.is_staff = is_staff
        self.is_superuser = is_superuser
        self.roles = roles or []
        self.permissions = permissions or []
        self.tenant_id = tenant_id

    async def has_perm(self, codename: str) -> bool:
        return codename in self.permissions

    async def has_role(self, role_name: str) -> bool:
        return role_name in self.roles

    async def has_model_perm(self, model_label: str, action: str) -> bool:
        return f"{model_label}.{action}" in self.permissions


class AnonymousMockUser(MockUser):
    """An unauthenticated mock user."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(
            user_id=0,
            username="anonymous",
            is_authenticated=False,
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def freeze_time(frozen_time: float):
    """Freeze time.time() to a fixed timestamp for testing expiry."""
    with patch("time.time", return_value=frozen_time):
        yield


# ---------------------------------------------------------------------------
# Malicious payload constants
# ---------------------------------------------------------------------------

XSS_PAYLOADS = [
    "<script>alert(1)</script>",
    '"><img src=x onerror=alert(1)>',
    "</script><script>alert(1)</script>",
]

SQL_INJECTION_PAYLOADS = [
    "' OR '1'='1",
    "1; DROP TABLE users",
    "' UNION SELECT password FROM users --",
]

PATH_TRAVERSAL_PAYLOADS = [
    "../secret.txt",
    "..%2f..%2fsecret.txt",
    "%252e%252e%252fsecret.txt",
    "/etc/passwd",
]

HEADER_INJECTION_PAYLOADS = [
    "safe\r\nSet-Cookie: admin=true",
    "value\nX-Injected: yes",
]

SSRF_PAYLOADS = [
    "http://127.0.0.1/",
    "http://localhost/",
    "http://169.254.169.254/",
    "file:///etc/passwd",
]

PROTOTYPE_POLLUTION_KEYS = [
    "__proto__",
    "constructor",
    "prototype",
]

COMMAND_INJECTION_PAYLOADS = [
    "; id",
    "&& whoami",
    "| cat /etc/passwd",
]
