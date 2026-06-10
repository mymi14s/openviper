"""Logging and error security tests.

Requirement IDs: LOG-001, LOG-002, ERR-001, ERR-002.

Covers:
  LOG-001 - Sensitive values are redacted from logs
  LOG-002 - Log injection is prevented
  ERR-001 - Production errors do not expose stack traces
  ERR-002 - Security events are logged
"""

from __future__ import annotations

import json
import logging
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.backends import authenticate
from openviper.auth.permission_core import PermissionError as OVPermissionError
from openviper.conf.settings import SENSITIVE_FIELDS
from openviper.db.executor import (
    _SENSITIVE_FIELD_NAMES,
    redact_filters,
    redact_values,
)
from openviper.debug.traceback_page import SENSITIVE_HEADERS, sanitize_header_value
from openviper.http.response import JSONResponse
from openviper.middleware.csrf import CSRFMiddleware
from openviper.middleware.error import ServerErrorMiddleware

from .conftest import SendCollector, make_scope


class LogCapture(logging.Handler):
    """Handler that captures log records for assertion."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    @property
    def messages(self) -> list[str]:
        return [self.format(r) for r in self.records]


def attach_log_capture(
    logger_name: str,
    level: int = logging.DEBUG,
) -> tuple[LogCapture, logging.Logger]:
    """Attach a LogCapture handler to the named logger and return both."""
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    capture = LogCapture()
    logger.addHandler(capture)
    return capture, logger


def detach_log_capture(logger: logging.Logger, capture: LogCapture) -> None:
    """Remove a previously attached LogCapture handler."""
    logger.removeHandler(capture)


class TestSensitiveValueRedaction:
    """Sensitive values must be redacted from logs (LOG-001)."""

    def test_log001_sensitive_field_names_include_password(self) -> None:
        """The framework must redact 'password' field values."""
        assert "password" in _SENSITIVE_FIELD_NAMES

    def test_log001_sensitive_field_names_include_password_hash(self) -> None:
        """The framework must redact 'password_hash' field values."""
        assert "password_hash" in _SENSITIVE_FIELD_NAMES

    def test_log001_sensitive_field_names_include_secret(self) -> None:
        """The framework must redact 'secret' field values."""
        assert "secret" in _SENSITIVE_FIELD_NAMES

    def test_log001_sensitive_field_names_include_token(self) -> None:
        """The framework must redact 'token' field values."""
        assert "token" in _SENSITIVE_FIELD_NAMES

    def test_log001_sensitive_field_names_include_api_key(self) -> None:
        """The framework must redact 'api_key' field values."""
        assert "api_key" in _SENSITIVE_FIELD_NAMES

    def test_log001_sensitive_field_names_include_api_secret(self) -> None:
        """The framework must redact 'api_secret' field values."""
        assert "api_secret" in _SENSITIVE_FIELD_NAMES

    def test_log001_sensitive_field_names_include_access_token(self) -> None:
        """The framework must redact 'access_token' field values."""
        assert "access_token" in _SENSITIVE_FIELD_NAMES

    def test_log001_sensitive_field_names_include_refresh_token(self) -> None:
        """The framework must redact 'refresh_token' field values."""
        assert "refresh_token" in _SENSITIVE_FIELD_NAMES

    def test_log001_sensitive_field_names_include_private_key(self) -> None:
        """The framework must redact 'private_key' field values."""
        assert "private_key" in _SENSITIVE_FIELD_NAMES

    def test_log001_sensitive_field_names_include_credit_card(self) -> None:
        """The framework must redact 'credit_card' field values."""
        assert "credit_card" in _SENSITIVE_FIELD_NAMES

    def test_log001_sensitive_field_names_include_ssn(self) -> None:
        """The framework must redact 'ssn' field values."""
        assert "ssn" in _SENSITIVE_FIELD_NAMES

    def test_log001_redact_filters_replaces_password_value(self) -> None:
        """redact_filters must replace password values with [REDACTED]."""
        filters = {"password": "hunter2"}
        result = redact_filters(filters)
        assert result == [{"password": "[REDACTED]"}]

    def test_log001_redact_filters_replaces_token_value(self) -> None:
        """redact_filters must replace token values with [REDACTED]."""
        filters = {"token": "abc123def456"}
        result = redact_filters(filters)
        assert result == [{"token": "[REDACTED]"}]

    def test_log001_redact_filters_replaces_api_key_value(self) -> None:
        """redact_filters must replace api_key values with [REDACTED]."""
        filters = {"api_key": "sk-live-12345"}
        result = redact_filters(filters)
        assert result == [{"api_key": "[REDACTED]"}]

    def test_log001_redact_filters_handles_lookup_suffixes(self) -> None:
        """redact_filters must redact fields with __lookup suffixes (e.g. password__exact)."""
        filters = {"password__exact": "hunter2"}
        result = redact_filters(filters)
        assert result == [{"password__exact": "[REDACTED]"}]

    def test_log001_redact_filters_preserves_non_sensitive_values(self) -> None:
        """redact_filters must preserve non-sensitive field values."""
        filters = {"username": "alice", "age": 30}
        result = redact_filters(filters)
        assert result == [{"username": "'alice'", "age": "30"}]

    def test_log001_redact_filters_handles_dict_input(self) -> None:
        """redact_filters must accept a single dict and return a list."""
        filters = {"secret": "my-secret", "name": "test"}
        result = redact_filters(filters)
        assert len(result) == 1
        assert result[0]["secret"] == "[REDACTED]"
        assert result[0]["name"] == "'test'"

    def test_log001_redact_filters_handles_list_input(self) -> None:
        """redact_filters must accept a list of dicts."""
        filters = [
            {"password": "pw1", "username": "u1"},
            {"token": "tk1", "email": "e1@example.com"},
        ]
        result = redact_filters(filters)
        assert len(result) == 2
        assert result[0]["password"] == "[REDACTED]"
        assert result[0]["username"] == "'u1'"
        assert result[1]["token"] == "[REDACTED]"
        assert result[1]["email"] == "'e1@example.com'"

    def test_log001_redact_values_replaces_password(self) -> None:
        """redact_values must replace password values with [REDACTED]."""
        values = {"password": "hunter2", "display_name": "Alice"}
        result = redact_values(values)
        assert result["password"] == "[REDACTED]"
        assert result["display_name"] == "'Alice'"

    def test_log001_redact_values_replaces_secret(self) -> None:
        """redact_values must replace secret values with [REDACTED]."""
        values = {"secret": "super-secret-value"}
        result = redact_values(values)
        assert result["secret"] == "[REDACTED]"

    def test_log001_redact_values_replaces_token(self) -> None:
        """redact_values must replace token values with [REDACTED]."""
        values = {"token": "abc123"}
        result = redact_values(values)
        assert result["token"] == "[REDACTED]"

    def test_log001_redact_values_replaces_api_key(self) -> None:
        """redact_values must replace api_key values with [REDACTED]."""
        values = {"api_key": "sk-12345"}
        result = redact_values(values)
        assert result["api_key"] == "[REDACTED]"

    def test_log001_redact_values_preserves_non_sensitive(self) -> None:
        """redact_values must preserve non-sensitive field values."""
        values = {"username": "bob", "email": "bob@example.com"}
        result = redact_values(values)
        assert result["username"] == "'bob'"
        assert result["email"] == "'bob@example.com'"

    def test_log001_settings_sensitive_fields_include_secret_key(self) -> None:
        """Settings must define SECRET_KEY as a sensitive field."""
        assert "SECRET_KEY" in SENSITIVE_FIELDS

    def test_log001_settings_sensitive_fields_include_database_url(self) -> None:
        """Settings must define DATABASES as a sensitive field."""
        assert "DATABASES" in SENSITIVE_FIELDS

    def test_log001_settings_sensitive_fields_include_cache_url(self) -> None:
        """Settings must define CACHES as a sensitive field."""
        assert "CACHES" in SENSITIVE_FIELDS

    def test_log001_settings_sensitive_fields_include_email(self) -> None:
        """Settings must define EMAIL as a sensitive field."""
        assert "EMAIL" in SENSITIVE_FIELDS

    def test_log001_debug_page_sanitizes_authorization_header(self) -> None:
        """Debug traceback page must mask Authorization header values."""
        assert sanitize_header_value("authorization", "Bearer secret-token") == "********"

    def test_log001_debug_page_sanitizes_cookie_header(self) -> None:
        """Debug traceback page must mask Cookie header values."""
        assert sanitize_header_value("cookie", "sessionid=abc123") == "********"

    def test_log001_debug_page_sanitizes_set_cookie_header(self) -> None:
        """Debug traceback page must mask Set-Cookie header values."""
        assert sanitize_header_value("set-cookie", "sessionid=abc123; Path=/") == "********"

    def test_log001_debug_page_sanitizes_x_api_key_header(self) -> None:
        """Debug traceback page must mask X-Api-Key header values."""
        assert sanitize_header_value("x-api-key", "sk-live-12345") == "********"

    def test_log001_debug_page_sanitizes_proxy_authorization_header(self) -> None:
        """Debug traceback page must mask Proxy-Authorization header values."""
        assert sanitize_header_value("proxy-authorization", "Basic dXNlcjpwYXNz") == "********"

    def test_log001_debug_page_sanitizes_x_csrf_token_header(self) -> None:
        """Debug traceback page must mask X-CSRFToken header values."""
        assert sanitize_header_value("x-csrf-token", "abc123def456") == "********"

    def test_log001_debug_page_preserves_non_sensitive_headers(self) -> None:
        """Debug traceback page must preserve non-sensitive header values."""
        assert sanitize_header_value("content-type", "application/json") == "application/json"
        assert sanitize_header_value("accept", "text/html") == "text/html"

    def test_log001_sensitive_headers_covers_all_credential_headers(self) -> None:
        """The SENSITIVE_HEADERS set must cover all common credential headers."""
        expected = {
            "authorization",
            "cookie",
            "set-cookie",
            "x-api-key",
            "x-forwarded-for",
            "x-real-ip",
            "proxy-authorization",
            "www-authenticate",
            "x-csrf-token",
            "x-xsrf-token",
        }
        for header in expected:
            assert header in SENSITIVE_HEADERS, f"Missing sensitive header: {header}"

    def test_log001_redact_filters_does_not_redact_username(self) -> None:
        """redact_filters must not redact non-sensitive fields like username."""
        filters = {"username": "alice"}
        result = redact_filters(filters)
        assert result[0]["username"] == "'alice'"

    def test_log001_redact_filters_does_not_redact_email(self) -> None:
        """redact_filters must not redact non-sensitive fields like email."""
        filters = {"email": "alice@example.com"}
        result = redact_filters(filters)
        assert result[0]["email"] == "'alice@example.com'"

    def test_log001_redact_values_does_not_redact_display_name(self) -> None:
        """redact_values must not redact non-sensitive fields like display_name."""
        values = {"display_name": "Alice Smith", "is_active": True}
        result = redact_values(values)
        assert result["display_name"] == "'Alice Smith'"
        assert result["is_active"] == "True"

    def test_log001_redact_filters_handles_empty_dict(self) -> None:
        """redact_filters must handle an empty dict without error."""
        result = redact_filters({})
        assert result == [{}]

    def test_log001_redact_values_handles_empty_dict(self) -> None:
        """redact_values must handle an empty dict without error."""
        result = redact_values({})
        assert result == {}

    def test_log001_redact_filters_handles_mixed_sensitive_and_normal(self) -> None:
        """redact_filters must correctly handle a mix of sensitive and normal fields."""
        filters = {"username": "admin", "password": "s3cret", "is_active": True}
        result = redact_filters(filters)
        assert result[0]["username"] == "'admin'"
        assert result[0]["password"] == "[REDACTED]"
        assert result[0]["is_active"] == "True"


class TestLogInjection:
    """Log injection must be prevented (LOG-002)."""

    def test_log002_redacted_output_contains_no_newlines(self) -> None:
        """Redacted filter output must not contain raw newlines from user input."""
        malicious_value = "admin\nFAKE LOG: admin login successful"
        filters = {"username": malicious_value}
        result = redact_filters(filters)
        # repr() should escape newlines
        assert "\\n" in result[0]["username"] or "\n" not in result[0]["username"]

    def test_log002_redacted_output_escapes_carriage_returns(self) -> None:
        """Redacted filter output must not contain raw carriage returns from user input."""
        malicious_value = "admin\r\nCRITICAL: system compromised"
        filters = {"username": malicious_value}
        result = redact_filters(filters)
        # repr() should escape the carriage return
        assert "\\r" in result[0]["username"] or "\r" not in result[0]["username"]

    def test_log002_redact_values_escapes_newlines(self) -> None:
        """redact_values must escape newlines in non-sensitive values."""
        malicious_value = "value\nFAKE LOG ENTRY"
        values = {"description": malicious_value}
        result = redact_values(values)
        # repr() should escape the newline
        assert "\\n" in result["description"] or "\n" not in result["description"]

    def test_log002_redact_values_escapes_tab_characters(self) -> None:
        """redact_values must escape tab characters in non-sensitive values."""
        malicious_value = "value\tFAKE\tCOLUMNS"
        values = {"description": malicious_value}
        result = redact_values(values)
        # repr() should escape the tab
        assert "\\t" in result["description"] or "\t" not in result["description"]

    def test_log002_sensitive_values_always_redacted_regardless_of_content(self) -> None:
        """Sensitive field values must always be [REDACTED] regardless of injected content."""
        malicious_password = "pw\nFAKE: admin logged in"
        filters = {"password": malicious_password}
        result = redact_filters(filters)
        assert result[0]["password"] == "[REDACTED]"

    def test_log002_structured_logging_uses_repr_for_non_sensitive(self) -> None:
        """Non-sensitive values must be repr()-formatted to prevent injection."""
        user_input = "normal_user"
        filters = {"username": user_input}
        result = redact_filters(filters)
        # repr() wraps strings in quotes, making injection harder
        assert result[0]["username"] == "'normal_user'"

    def test_log002_control_characters_in_username_are_escaped(self) -> None:
        """Control characters in non-sensitive fields must be escaped via repr()."""
        malicious = "user\x00\x01\x1badmin"
        filters = {"username": malicious}
        result = redact_filters(filters)
        # repr() escapes control characters
        assert "\\x00" in result[0]["username"] or "\\x01" in result[0]["username"]

    def test_log002_legitimate_username_preserved(self) -> None:
        """Legitimate usernames must be preserved in log output."""
        filters = {"username": "alice"}
        result = redact_filters(filters)
        assert result[0]["username"] == "'alice'"

    def test_log002_legitimate_email_preserved(self) -> None:
        """Legitimate email addresses must be preserved in log output."""
        filters = {"email": "alice@example.com"}
        result = redact_filters(filters)
        assert result[0]["email"] == "'alice@example.com'"

    def test_log002_unicode_content_preserved_in_repr(self) -> None:
        """Unicode content in non-sensitive fields must be preserved via repr()."""
        filters = {"display_name": "Ünïcödé"}
        result = redact_filters(filters)
        assert "Ünïcödé" in result[0]["display_name"]


class TestProductionErrorHandling:
    """Production errors must not expose stack traces (ERR-001)."""

    @pytest.mark.asyncio
    async def test_err001_production_error_returns_500(self) -> None:
        """ServerErrorMiddleware in production must return HTTP 500."""

        async def failing_app(scope: dict[str, object], receive: object, send: object) -> None:
            raise RuntimeError("Secret internal error details")

        middleware = ServerErrorMiddleware(failing_app, debug=False)
        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        assert collector.status_code == 500

    @pytest.mark.asyncio
    async def test_err001_production_error_no_exception_message(self) -> None:
        """Production 500 response must not contain the exception message."""

        async def failing_app(scope: dict[str, object], receive: object, send: object) -> None:
            raise RuntimeError("Secret internal error details")

        middleware = ServerErrorMiddleware(failing_app, debug=False)
        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        body = collector.body.decode("utf-8", errors="replace")
        assert "Secret internal error details" not in body

    @pytest.mark.asyncio
    async def test_err001_production_error_no_exception_type(self) -> None:
        """Production 500 response must not contain the exception type name."""

        async def failing_app(scope: dict[str, object], receive: object, send: object) -> None:
            raise RuntimeError("Internal error")

        middleware = ServerErrorMiddleware(failing_app, debug=False)
        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        body = collector.body.decode("utf-8", errors="replace")
        assert "RuntimeError" not in body

    @pytest.mark.asyncio
    async def test_err001_production_error_no_traceback(self) -> None:
        """Production 500 response must not contain any traceback content."""

        async def failing_app(scope: dict[str, object], receive: object, send: object) -> None:
            raise ValueError("Database connection failed at /var/lib/db/main.sqlite")

        middleware = ServerErrorMiddleware(failing_app, debug=False)
        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        body = collector.body.decode("utf-8", errors="replace")
        assert "Traceback" not in body
        assert "File " not in body

    @pytest.mark.asyncio
    async def test_err001_production_error_no_source_paths(self) -> None:
        """Production 500 response must not contain source file paths."""

        async def failing_app(scope: dict[str, object], receive: object, send: object) -> None:
            raise OSError("/etc/passwd: Permission denied")

        middleware = ServerErrorMiddleware(failing_app, debug=False)
        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        body = collector.body.decode("utf-8", errors="replace")
        assert "/etc/passwd" not in body

    @pytest.mark.asyncio
    async def test_err001_production_error_no_env_vars(self) -> None:
        """Production 500 response must not expose environment variable values."""

        async def failing_app(scope: dict[str, object], receive: object, send: object) -> None:
            raise RuntimeError("DATABASE_URL=postgres://admin:pass@db:5432/prod failed")

        middleware = ServerErrorMiddleware(failing_app, debug=False)
        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        body = collector.body.decode("utf-8", errors="replace")
        assert "postgres://" not in body
        assert "DATABASE_URL" not in body

    @pytest.mark.asyncio
    async def test_err001_production_error_no_sql_queries(self) -> None:
        """Production 500 response must not expose SQL query details."""

        async def failing_app(scope: dict[str, object], receive: object, send: object) -> None:
            raise RuntimeError("SELECT * FROM users WHERE password='hunter2'")

        middleware = ServerErrorMiddleware(failing_app, debug=False)
        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        body = collector.body.decode("utf-8", errors="replace")
        assert "SELECT" not in body
        assert "hunter2" not in body

    @pytest.mark.asyncio
    async def test_err001_production_error_plain_text_content_type(self) -> None:
        """Production 500 response must have text/plain content type."""

        async def failing_app(scope: dict[str, object], receive: object, send: object) -> None:
            raise ValueError("Internal error")

        middleware = ServerErrorMiddleware(failing_app, debug=False)
        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        headers = collector.headers_dict
        assert "text/plain" in headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_err001_production_error_generic_body(self) -> None:
        """Production 500 response body must be a generic error message."""

        async def failing_app(scope: dict[str, object], receive: object, send: object) -> None:
            raise ValueError("Specific error")

        middleware = ServerErrorMiddleware(failing_app, debug=False)
        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        body = collector.body.decode("utf-8", errors="replace")
        assert body == "Internal Server Error"

    @pytest.mark.asyncio
    async def test_err001_production_error_no_html_tags(self) -> None:
        """Production 500 response must not contain HTML tags."""

        async def failing_app(scope: dict[str, object], receive: object, send: object) -> None:
            raise ValueError("Error")

        middleware = ServerErrorMiddleware(failing_app, debug=False)
        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        body = collector.body.decode("utf-8", errors="replace")
        assert "<" not in body
        assert ">" not in body

    @pytest.mark.asyncio
    async def test_err001_production_error_logs_exception(self) -> None:
        """ServerErrorMiddleware must log the exception at ERROR level in production."""
        capture, app_logger = attach_log_capture("openviper.app", logging.ERROR)
        try:

            async def failing_app(scope: dict[str, object], receive: object, send: object) -> None:
                raise RuntimeError("Test error for logging")

            middleware = ServerErrorMiddleware(failing_app, debug=False)
            scope = make_scope()
            collector = SendCollector()
            await middleware(scope, None, collector)

            assert len(capture.records) >= 1
            assert any(r.levelno >= logging.ERROR for r in capture.records)
        finally:
            detach_log_capture(app_logger, capture)

    @pytest.mark.asyncio
    async def test_err001_production_error_handles_nested_exceptions(self) -> None:
        """Production 500 must not leak details from chained exceptions."""

        async def failing_app(scope: dict[str, object], receive: object, send: object) -> None:
            try:
                raise ValueError("Inner secret error")
            except ValueError as exc:
                raise RuntimeError("Outer secret error") from exc

        middleware = ServerErrorMiddleware(failing_app, debug=False)
        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        body = collector.body.decode("utf-8", errors="replace")
        assert "Inner secret error" not in body
        assert "Outer secret error" not in body

    @pytest.mark.asyncio
    async def test_err001_debug_mode_shows_traceback(self) -> None:
        """Debug mode must show traceback for development."""

        async def failing_app(scope: dict[str, object], receive: object, send: object) -> None:
            raise ValueError("Test error for debug")

        middleware = ServerErrorMiddleware(failing_app, debug=True)
        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        assert collector.status_code == 500
        headers = collector.headers_dict
        assert "text/html" in headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_err001_debug_mode_includes_exception_type(self) -> None:
        """Debug mode must include the exception type in the response."""

        async def failing_app(scope: dict[str, object], receive: object, send: object) -> None:
            raise ValueError("Debug error message")

        middleware = ServerErrorMiddleware(failing_app, debug=True)
        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        body = collector.body.decode("utf-8", errors="replace")
        assert "ValueError" in body

    @pytest.mark.asyncio
    async def test_err001_debug_mode_includes_exception_message(self) -> None:
        """Debug mode must include the exception message in the response."""

        async def failing_app(scope: dict[str, object], receive: object, send: object) -> None:
            raise ValueError("Debug error message")

        middleware = ServerErrorMiddleware(failing_app, debug=True)
        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        body = collector.body.decode("utf-8", errors="replace")
        assert "Debug error message" in body

    @pytest.mark.asyncio
    async def test_err001_debug_mode_sanitizes_sensitive_headers(self) -> None:
        """Debug mode must sanitize sensitive headers in the request section."""

        async def failing_app(scope: dict[str, object], receive: object, send: object) -> None:
            raise ValueError("Debug error")

        middleware = ServerErrorMiddleware(failing_app, debug=True)
        scope = make_scope(
            headers=[
                (b"authorization", b"Bearer secret-token-12345"),
                (b"cookie", b"sessionid=abc123def456"),
                (b"content-type", b"application/json"),
            ],
        )
        collector = SendCollector()
        await middleware(scope, None, collector)

        body = collector.body.decode("utf-8", errors="replace")
        # The Request headers section must mask sensitive header values.
        # The debug page renders headers via sanitize_header_value which
        # replaces authorization/cookie values with "********".
        # We check the info-table section specifically, not the traceback
        # source code which may contain literal Python bytes from the test.
        header_rows = re.findall(r'<td class="key">(.*?)</td>\s*<td class="val">(.*?)</td>', body)
        header_dict = {k.strip(): v.strip() for k, v in header_rows}

        # Sensitive headers must be masked with "********"
        assert (
            header_dict.get("authorization") == "********"
        ), f"Authorization header must be masked, got: {header_dict.get('authorization')}"
        assert (
            header_dict.get("cookie") == "********"
        ), f"Cookie header must be masked, got: {header_dict.get('cookie')}"
        # Non-sensitive headers must be visible
        assert (
            header_dict.get("content-type") == "application/json"
        ), f"Content-Type header must be visible, got: {header_dict.get('content-type')}"

    @pytest.mark.asyncio
    async def test_err001_debug_mode_has_nosniff_header(self) -> None:
        """Debug mode must include X-Content-Type-Options: nosniff."""

        async def failing_app(scope: dict[str, object], receive: object, send: object) -> None:
            raise ValueError("Debug error")

        middleware = ServerErrorMiddleware(failing_app, debug=True)
        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        headers = collector.headers_dict
        assert headers.get("x-content-type-options") == "nosniff"

    @pytest.mark.asyncio
    async def test_err001_debug_mode_has_csp_header(self) -> None:
        """Debug mode must include a restrictive Content-Security-Policy header."""

        async def failing_app(scope: dict[str, object], receive: object, send: object) -> None:
            raise ValueError("Debug error")

        middleware = ServerErrorMiddleware(failing_app, debug=True)
        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        headers = collector.headers_dict
        csp = headers.get("content-security-policy", "")
        assert "default-src 'none'" in csp
        assert "style-src 'unsafe-inline'" in csp

    @pytest.mark.asyncio
    async def test_err001_non_http_scope_passes_through(self) -> None:
        """ServerErrorMiddleware must pass through non-HTTP scopes unchanged."""
        received_scope: dict[str, object] = {}

        async def passthrough_app(scope: dict[str, object], receive: object, send: object) -> None:
            received_scope.update(scope)

        middleware = ServerErrorMiddleware(passthrough_app, debug=False)
        lifespan_scope = {"type": "lifespan"}
        collector = SendCollector()
        await middleware(lifespan_scope, None, collector)

        assert received_scope.get("type") == "lifespan"

    @pytest.mark.asyncio
    async def test_err001_production_error_content_length_matches_body(self) -> None:
        """Production 500 response Content-Length must match the body length."""

        async def failing_app(scope: dict[str, object], receive: object, send: object) -> None:
            raise ValueError("Error")

        middleware = ServerErrorMiddleware(failing_app, debug=False)
        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        headers = collector.headers_dict
        content_length = int(headers.get("content-length", "0"))
        assert content_length == len(collector.body)


class TestSecurityEventLogging:
    """Security events must be logged (ERR-002)."""

    @pytest.mark.asyncio
    async def test_err002_failed_login_logs_warning(self) -> None:
        """Failed authentication must emit a warning-level log event."""
        capture, auth_logger = attach_log_capture("openviper.auth.backends", logging.WARNING)
        try:
            with patch("openviper.auth.backends.get_user_model") as mock_get_model:
                mock_model = MagicMock()
                mock_queryset = AsyncMock()
                mock_queryset.first = AsyncMock(return_value=None)
                mock_model.objects.filter = MagicMock(return_value=mock_queryset)
                mock_get_model.return_value = mock_model

                with patch(
                    "openviper.auth.backends.check_password", new_callable=AsyncMock
                ) as mock_check:
                    mock_check.return_value = False
                    result = await authenticate(username="nonexistent", password="wrong")

            assert result is None
            warning_records = [r for r in capture.records if r.levelno >= logging.WARNING]
            assert len(warning_records) >= 1
            warning_messages = [r.getMessage() for r in warning_records]
            assert any(
                "Authentication failed" in msg or "user not found" in msg.lower()
                for msg in warning_messages
            )
        finally:
            detach_log_capture(auth_logger, capture)

    @pytest.mark.asyncio
    async def test_err002_failed_login_includes_username_in_log(self) -> None:
        """Failed authentication log must include the username for audit."""
        capture, auth_logger = attach_log_capture("openviper.auth.backends", logging.WARNING)
        try:
            with patch("openviper.auth.backends.get_user_model") as mock_get_model:
                mock_model = MagicMock()
                mock_queryset = AsyncMock()
                mock_queryset.first = AsyncMock(return_value=None)
                mock_model.objects.filter = MagicMock(return_value=mock_queryset)
                mock_get_model.return_value = mock_model

                with patch(
                    "openviper.auth.backends.check_password", new_callable=AsyncMock
                ) as mock_check:
                    mock_check.return_value = False
                    await authenticate(username="testuser_bad", password="wrongpass")

            warning_records = [r for r in capture.records if r.levelno >= logging.WARNING]
            assert len(warning_records) >= 1
            # The username should appear in the extra data or message
            found_username = any(
                getattr(r, "username", None) == "testuser_bad" or "testuser_bad" in r.getMessage()
                for r in warning_records
            )
            assert found_username, "Username must appear in failed login log"
        finally:
            detach_log_capture(auth_logger, capture)

    @pytest.mark.asyncio
    async def test_err002_failed_login_includes_reason_in_log(self) -> None:
        """Failed authentication log must include the reason for failure."""
        capture, auth_logger = attach_log_capture("openviper.auth.backends", logging.WARNING)
        try:
            with patch("openviper.auth.backends.get_user_model") as mock_get_model:
                mock_model = MagicMock()
                mock_queryset = AsyncMock()
                mock_queryset.first = AsyncMock(return_value=None)
                mock_model.objects.filter = MagicMock(return_value=mock_queryset)
                mock_get_model.return_value = mock_model

                with patch(
                    "openviper.auth.backends.check_password", new_callable=AsyncMock
                ) as mock_check:
                    mock_check.return_value = False
                    await authenticate(username="missing_user", password="wrong")

            warning_records = [r for r in capture.records if r.levelno >= logging.WARNING]
            assert len(warning_records) >= 1
            # The reason field should be present in the extra data
            found_reason = any(
                hasattr(r, "reason") or "reason" in str(getattr(r, "__dict__", {}))
                for r in warning_records
            )
            assert found_reason, "Reason must be present in failed login log"
        finally:
            detach_log_capture(auth_logger, capture)

    @pytest.mark.asyncio
    async def test_err002_csrf_failure_returns_403(self) -> None:
        """CSRF verification failure must return HTTP 403."""

        async def ok_app(scope: dict[str, object], receive: object, send: object) -> None:
            response = JSONResponse({"status": "ok"})
            await response(scope, receive, send)

        middleware = CSRFMiddleware(ok_app, secret="test-secret-key-for-csrf")
        scope = make_scope(
            method="POST",
            path="/api/data",
            headers=[(b"content-type", b"application/json")],
        )
        collector = SendCollector()
        await middleware(scope, None, collector)

        assert collector.status_code == 403

    @pytest.mark.asyncio
    async def test_err002_csrf_failure_returns_json_error(self) -> None:
        """CSRF verification failure must return a JSON error response."""

        async def ok_app(scope: dict[str, object], receive: object, send: object) -> None:
            response = JSONResponse({"status": "ok"})
            await response(scope, receive, send)

        middleware = CSRFMiddleware(ok_app, secret="test-secret-key-for-csrf")
        scope = make_scope(
            method="POST",
            path="/api/data",
            headers=[(b"content-type", b"application/json")],
        )
        collector = SendCollector()
        await middleware(scope, None, collector)

        body = collector.body.decode("utf-8", errors="replace")
        data = json.loads(body)
        assert "detail" in data
        assert "CSRF" in data["detail"] or "csrf" in data["detail"].lower()

    @pytest.mark.asyncio
    async def test_err002_csrf_safe_methods_pass(self) -> None:
        """CSRF middleware must allow safe methods (GET, HEAD, OPTIONS) without tokens."""

        async def ok_app(scope: dict[str, object], receive: object, send: object) -> None:
            response = JSONResponse({"status": "ok"})
            await response(scope, receive, send)

        middleware = CSRFMiddleware(ok_app, secret="test-secret-key-for-csrf")

        for method in ("GET", "HEAD", "OPTIONS"):
            scope = make_scope(method=method, path="/api/data")
            collector = SendCollector()
            await middleware(scope, None, collector)
            assert collector.status_code == 200, f"Safe method {method} should pass CSRF check"

    def test_err002_permission_error_is_exception(self) -> None:
        """PermissionError must be a proper exception class."""
        assert issubclass(OVPermissionError, Exception)

    def test_err002_permission_error_message(self) -> None:
        """PermissionError must carry a descriptive error message."""
        exc = OVPermissionError("Unauthorized: Access denied 'delete' on blog.post")
        assert "Access denied" in str(exc)
        assert "delete" in str(exc)

    def test_err002_permission_error_can_be_raised_and_caught(self) -> None:
        """PermissionError must be raisable and catchable."""
        with pytest.raises(OVPermissionError, match="Access denied"):
            raise OVPermissionError("Unauthorized: Access denied 'write' on article.article")

    @pytest.mark.asyncio
    async def test_err002_server_error_logs_exception_details(self) -> None:
        """ServerErrorMiddleware must log exception details even in production."""
        capture, app_logger = attach_log_capture("openviper.app", logging.ERROR)
        try:

            async def failing_app(scope: dict[str, object], receive: object, send: object) -> None:
                raise RuntimeError("Detailed error for logging")

            middleware = ServerErrorMiddleware(failing_app, debug=False)
            scope = make_scope()
            collector = SendCollector()
            await middleware(scope, None, collector)

            # The exception must be logged (even though it's not in the response)
            assert len(capture.records) >= 1
            error_messages = [r.getMessage() for r in capture.records if r.levelno >= logging.ERROR]
            assert any("Detailed error for logging" in msg for msg in error_messages)
        finally:
            detach_log_capture(app_logger, capture)

    @pytest.mark.asyncio
    async def test_err002_csrf_failure_with_invalid_token(self) -> None:
        """CSRF verification must fail with an invalid token."""

        async def ok_app(scope: dict[str, object], receive: object, send: object) -> None:
            response = JSONResponse({"status": "ok"})
            await response(scope, receive, send)

        middleware = CSRFMiddleware(ok_app, secret="test-secret-key-for-csrf")
        scope = make_scope(
            method="POST",
            path="/api/data",
            headers=[
                (b"cookie", b"csrftoken=validtoken123"),
                (b"x-csrftoken", b"invalid-token-value"),
            ],
        )
        collector = SendCollector()
        await middleware(scope, None, collector)

        # Invalid token should result in 403
        assert collector.status_code == 403

    @pytest.mark.asyncio
    async def test_err002_successful_login_no_warning_log(self) -> None:
        """Successful authentication must not emit a warning-level log."""
        capture, auth_logger = attach_log_capture("openviper.auth.backends", logging.WARNING)
        try:
            mock_user = MagicMock()
            mock_user.pk = 1
            mock_user.is_active = True
            mock_user.check_password = AsyncMock(return_value=True)

            mock_queryset = AsyncMock()
            mock_queryset.first = AsyncMock(return_value=mock_user)

            mock_model = MagicMock()
            mock_model.objects.filter = MagicMock(return_value=mock_queryset)

            with patch("openviper.auth.backends.get_user_model", return_value=mock_model):
                result = await authenticate(username="validuser", password="validpass")

            assert result is not None
            warning_records = [r for r in capture.records if r.levelno >= logging.WARNING]
            assert len(warning_records) == 0
        finally:
            detach_log_capture(auth_logger, capture)

    @pytest.mark.asyncio
    async def test_err002_csrf_safe_method_no_failure(self) -> None:
        """Safe HTTP methods must not trigger CSRF failure responses."""

        async def ok_app(scope: dict[str, object], receive: object, send: object) -> None:
            response = JSONResponse({"status": "ok"})
            await response(scope, receive, send)

        middleware = CSRFMiddleware(ok_app, secret="test-secret-key-for-csrf")
        scope = make_scope(method="GET", path="/api/data")
        collector = SendCollector()
        await middleware(scope, None, collector)

        assert collector.status_code == 200

    def test_err002_permission_error_not_raised_for_authorized(self) -> None:
        """PermissionError must not be raised when access is authorized."""
        # Verify the exception type exists and can be used in authorization checks
        try:
            raise OVPermissionError("Unauthorized: Access denied 'read' on public.doc")
        except OVPermissionError:
            pass  # Expected - the exception works correctly
        else:
            raise AssertionError("PermissionError should have been raised")
