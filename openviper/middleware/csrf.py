"""CSRF protection middleware."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import TYPE_CHECKING, cast
from urllib.parse import parse_qs

from openviper.conf import settings
from openviper.http.response import JSONResponse
from openviper.middleware.base import ASGIApp, BaseMiddleware

if TYPE_CHECKING:
    from openviper.http.types import ASGIMessage, ASGIReceive, ASGIScope, ASGISend

CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_COOKIE_NAME = "csrftoken"
CSRF_HEADER_NAME = "x-csrftoken"
CSRF_FORM_FIELD = "csrfmiddlewaretoken"
CSRF_MAX_BODY_SIZE = 2 * 1024 * 1024


def generate_csrf_token() -> str:
    return secrets.token_hex(32)


def mask_csrf_token(token: str, secret: str) -> str:
    """Create a per-request masked token for the HTML form."""
    salt = secrets.token_hex(16)
    signature = hmac.new(secret.encode(), f"{salt}{token}".encode(), hashlib.sha256).hexdigest()
    return f"{salt}{signature}"


def verify_csrf_token(cookie_token: str, submitted_token: str, secret: str) -> bool:
    """Constant-time verify that the submitted token matches the cookie."""
    if len(submitted_token) < 96:
        return False
    salt = submitted_token[:32]
    expected = hmac.new(
        secret.encode(), f"{salt}{cookie_token}".encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(submitted_token[32:], expected)


def extract_cookie_value(cookie_header: str, cookie_name: str) -> str:
    """Extract a single cookie value without full cookie parsing.

    Handles quoted cookie values per RFC 6265 by stripping surrounding
    DQUOTE characters.
    """
    if not cookie_header:
        return ""

    search_str = f"{cookie_name}="
    parts = cookie_header.split(";")

    for part in parts:
        part = part.strip()
        if part.startswith(search_str):
            value = part[len(search_str) :]
            if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            return value

    return ""


class CSRFMiddleware(BaseMiddleware):
    """CSRF protection via double-submit cookie pattern.

    Safe methods (GET, HEAD, OPTIONS) pass through without validation.
    Unsafe methods require a matching ``X-CSRFToken`` header or form field.

    Args:
        app: Next ASGI app.
        secret: Signing secret (uses settings.SECRET_KEY by default).
        cookie_name: Name of the CSRF cookie.
        header_name: Name of the HTTP header to check.
        exempt_paths: Paths that skip CSRF validation.
    """

    def __init__(
        self,
        app: ASGIApp,
        secret: str = "",
        cookie_name: str = CSRF_COOKIE_NAME,
        header_name: str = CSRF_HEADER_NAME,
        exempt_paths: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self._secret = secret
        self._cookie_name = cookie_name
        self._header_name = header_name
        self._exempt_paths = set(exempt_paths or [])

    def get_secret(self) -> str:
        if self._secret:
            return self._secret
        try:
            key = settings.SECRET_KEY
        except Exception as exc:
            raise RuntimeError(
                "CSRFMiddleware requires settings.SECRET_KEY or an explicit 'secret' argument."
            ) from exc
        if not key:
            raise RuntimeError("CSRFMiddleware requires a non-empty SECRET_KEY.")
        return cast("str", key)

    async def extract_form_token(
        self,
        receive: ASGIReceive,
    ) -> tuple[str, ASGIReceive]:
        """Read the request body and extract the CSRF form field value.

        Returns the token string and a new ``receive`` callable that replays
        the already-consumed body so downstream middleware/apps still see it.
        Aborts reading after CSRF_MAX_BODY_SIZE bytes to prevent DoS via
        unbounded body consumption.
        """
        body_parts: list[bytes] = []
        total_size = 0
        while True:
            message = await receive()
            chunk = cast("bytes", message.get("body", b""))
            if chunk:
                total_size += len(chunk)
                if total_size > CSRF_MAX_BODY_SIZE:
                    break
                body_parts.append(chunk)
            if not cast("bool", message.get("more_body", False)):
                break

        body = b"".join(body_parts)
        submitted_token = ""
        parsed = parse_qs(body.decode("latin-1"), keep_blank_values=True)
        values = parsed.get(CSRF_FORM_FIELD)
        if values:
            submitted_token = values[0]

        # ASGI contract requires an unread receive callable for downstream.
        replayed = False

        async def replay_receive() -> ASGIMessage:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}

        return submitted_token, replay_receive

    async def __call__(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = cast("str", scope.get("method", "GET")).upper()
        path = cast("str", scope.get("path", "/"))

        cookie_raw = b""
        submitted_raw = b""
        header_name_lower = self._header_name.encode("latin-1")
        headers = cast("list[tuple[bytes, bytes]]", scope.get("headers", []))
        for name, value in headers:
            lower = name.lower()
            if lower == b"cookie":
                cookie_raw = value
            elif lower == header_name_lower:
                submitted_raw = value

        cookie_header = cookie_raw.decode("latin-1") if cookie_raw else ""
        csrf_cookie = extract_cookie_value(cookie_header, self._cookie_name)

        if path not in self._exempt_paths and method not in CSRF_SAFE_METHODS:
            origin_raw = b""
            for name, value in headers:
                if name.lower() == b"origin":
                    origin_raw = value
                    break
            is_trusted = False
            if origin_raw:
                origin = origin_raw.decode("latin-1").rstrip("/")
                trusted: tuple[str, ...] = getattr(settings, "CSRF_TRUSTED_ORIGINS", ())
                is_trusted = any(origin == t.rstrip("/") for t in trusted)

            if not is_trusted:
                submitted = submitted_raw.decode("latin-1") if submitted_raw else ""
                if not submitted:
                    content_type = b""
                    for name, value in headers:
                        if name.lower() == b"content-type":
                            content_type = value
                            break
                    if b"application/x-www-form-urlencoded" in content_type:
                        submitted, receive = await self.extract_form_token(receive)

                secret = self.get_secret()
                if (
                    not csrf_cookie
                    or not submitted
                    or not verify_csrf_token(csrf_cookie, submitted, secret)
                ):
                    response = JSONResponse(
                        {"detail": "CSRF verification failed."}, status_code=403
                    )
                    await response(scope, receive, send)
                    return

        async def send_wrapper(message: ASGIMessage) -> None:
            if message["type"] == "http.response.start" and not csrf_cookie:
                new_token = generate_csrf_token()
                headers = cast("list[tuple[bytes, bytes]]", message.get("headers", []))
                headers = list(headers)

                cookie_value = f"{self._cookie_name}={new_token}; Path=/"
                if getattr(settings, "CSRF_COOKIE_SECURE", False) or scope.get("scheme") == "https":
                    cookie_value += "; Secure"
                if getattr(settings, "CSRF_COOKIE_HTTPONLY", False):
                    cookie_value += "; HttpOnly"

                samesite = getattr(settings, "CSRF_COOKIE_SAMESITE", "Lax")
                if samesite:
                    cookie_value += f"; SameSite={samesite}"

                max_age = getattr(settings, "CSRF_COOKIE_AGE", None)
                if max_age is not None:
                    cookie_value += f"; Max-Age={int(max_age)}"

                headers.append((b"set-cookie", cookie_value.encode("latin-1")))
                message["headers"] = headers

            await send(message)

        await self.app(scope, receive, send_wrapper)
