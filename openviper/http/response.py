"""HTTP Response classes for OpenViper."""

from __future__ import annotations

import datetime
import email.utils
import gzip
import importlib
import json
import logging
import mimetypes
import os
import re
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.parse import unquote, urlparse

import anyio
import orjson
from pydantic import BaseModel

from openviper.conf import settings
from openviper.core.context import current_request, current_router
from openviper.template.environment import get_jinja2_env
from openviper.utils.datastructures import MutableHeaders

if TYPE_CHECKING:
    from openviper.http.types import (
        ASGIMessage,
        ASGIReceive,
        ASGIScope,
        ASGISend,
        JsonValue,
        TemplateContext,
    )

logger = logging.getLogger(__name__)

MISSING_SENTINEL = object()

# Distinguish "namespace:route_name" from bare route names.
NAMESPACED_ROUTE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*:[A-Za-z_][A-Za-z0-9_]*$")


def strip_host_port(raw: str) -> str:
    """Return host without port, preserving IPv6 bracket handling."""
    if raw.startswith("["):
        bracket_end = raw.find("]")
        if bracket_end != -1:
            return raw[1:bracket_end]
        return raw[1:]
    if ":" in raw:
        return raw.rsplit(":", 1)[0]
    return raw


def is_allowed_redirect_host(host: str, allowed_hosts: Sequence[str]) -> bool:
    """Return whether *host* matches exact or leading-dot host allowlists."""
    normalized_host = host.rstrip(".").lower()
    if not normalized_host:
        return False
    for raw_pattern in allowed_hosts:
        pattern = strip_host_port(raw_pattern).rstrip(".").lower()
        if pattern == "*":
            return True
        if pattern.startswith("."):
            suffix = pattern[1:]
            if normalized_host == suffix or normalized_host.endswith(pattern):
                return True
        elif normalized_host == pattern:
            return True
    return False


def json_encode(
    content: JsonValue,
    *,
    default: Callable[[object], object],
    indent: int | None,
) -> bytes:
    """Serialize *content* to JSON bytes using orjson (C extension)."""
    option: int | None = None
    if indent == 2:
        option = orjson.OPT_INDENT_2
    elif indent is not None:
        # orjson only supports indent=2; fall back to stdlib for other values.
        return json.dumps(content, default=default, indent=indent).encode("utf-8")
    return orjson.dumps(content, default=default, option=option)


@lru_cache(maxsize=32)
def compute_template_search_paths(
    base_dir: str, installed_apps: tuple[str, ...]
) -> tuple[str, ...]:
    """Compute and cache template search paths for given base_dir and installed apps.

    This avoids repeated filesystem checks and module imports on every template render.
    Cached by base_dir and installed_apps tuple since these rarely change at runtime.
    """
    search_paths: list[str] = [base_dir]
    for app_path in installed_apps:
        try:
            mod = importlib.import_module(app_path)
            if hasattr(mod, "__file__") and mod.__file__:
                app_dir = Path(mod.__file__).parent
                app_templates = app_dir / "templates"
                if app_templates.is_dir():
                    search_paths.append(str(app_templates))
        except ImportError, AttributeError:
            continue
    return tuple(search_paths)


def get_jinja2_env_cached(search_paths: tuple[str, ...]) -> object:
    """Return a cached Jinja2 :class:`Environment` keyed by *search_paths*.

    Delegates to :func:`openviper.template.environment.get_jinja2_env` which
    owns the LRU cache and invokes the plugin loader on first construction.
    """
    return get_jinja2_env(search_paths)


def cache_clear() -> None:
    """Clear the underlying LRU caches - `lru_cache.cache_clear``."""
    get_jinja2_env.cache_clear()
    compute_template_search_paths.cache_clear()


get_jinja2_env_cached.cache_clear = cache_clear


async def send_complete_response(
    send: ASGISend,
    status: int,
    headers: list[list[bytes]] | list[tuple[bytes, bytes]],
    body: bytes = b"",
) -> None:
    """Send a complete ASGI response (start event + final body event)."""
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body, "more_body": False})


class Response:
    """Base HTTP response.

    Args:
        content: Response body. Bytes, str, or None.
        status_code: HTTP status code (default 200).
        headers: Optional dict of headers to set.
        media_type: Content-Type MIME type.
    """

    __slots__ = ("status_code", "media_type", "_headers", "body")

    _MEDIA_TYPE: str | None = None
    charset: str = "utf-8"

    def __init__(
        self,
        content: bytes | str | None = None,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        media_type: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.media_type = media_type or type(self)._MEDIA_TYPE
        self._headers = MutableHeaders(raw=self.build_raw_headers(headers or {}))
        self.body = self.encode(content)

    def encode(self, content: bytes | str | None) -> bytes:
        if content is None:
            return b""
        if isinstance(content, bytes):
            return content
        if isinstance(content, str):
            return content.encode(self.charset)
        raise TypeError(f"Response content must be str or bytes, not {type(content).__name__}")

    def build_raw_headers(self, extra: dict[str, str]) -> list[list[bytes]]:
        raw: list[list[bytes]] = []
        content_type = self.media_type
        if content_type and "charset" not in content_type and "text" in content_type:
            content_type = f"{content_type}; charset={self.charset}"
        if content_type:
            raw.append([b"content-type", content_type.encode("latin-1")])
        for k, v in extra.items():
            raw.append([k.lower().encode("latin-1"), v.encode("latin-1")])
        return raw

    @property
    def headers(self) -> MutableHeaders:
        return self._headers

    def set_cookie(
        self,
        key: str,
        value: str = "",
        max_age: int | None = None,
        expires: int | None = None,
        path: str = "/",
        domain: str | None = None,
        secure: bool = False,
        httponly: bool = False,
        samesite: str = "lax",
    ) -> None:
        """Append a Set-Cookie header."""
        # Prevent CR/LF injection in cookie names and values.
        if "\r" in key or "\n" in key:
            raise ValueError(f"Cookie name must not contain CR or LF: {key!r}")
        if "\r" in value or "\n" in value:
            raise ValueError(f"Cookie value must not contain CR or LF: {value!r}")
        cookie = f"{key}={value}"
        if max_age is not None:
            cookie += f"; Max-Age={max_age}"
        if expires is not None:
            if isinstance(expires, int):
                expires_time = time.gmtime(expires)
                expires_str = email.utils.formatdate(
                    timeval=time.mktime(expires_time),
                    localtime=False,
                    usegmt=True,
                )
                cookie += f"; Expires={expires_str}"
            else:
                cookie += f"; Expires={expires}"
        if path:
            cookie += f"; Path={path}"
        if domain:
            cookie += f"; Domain={domain}"
        if secure:
            cookie += "; Secure"
        if httponly:
            cookie += "; HttpOnly"
        cookie += f"; SameSite={samesite.capitalize()}"
        # SameSite=None without Secure violates RFC 6265bis.
        if samesite.lower() == "none" and not secure:
            raise ValueError("Cookies with SameSite=None must also set Secure=True")
        self._headers.append("set-cookie", cookie)

    def delete_cookie(self, key: str, path: str = "/", domain: str | None = None) -> None:
        self.set_cookie(key, "", max_age=0, path=path, domain=domain)

    async def __call__(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        body = self.body
        if body:
            self._headers.set("content-length", str(len(body)))
        await send_complete_response(send, self.status_code, self._headers.raw, body)


class JSONResponse(Response):
    """JSON response serialised with orjson."""

    __slots__ = ()
    _MEDIA_TYPE = "application/json"

    def __init__(
        self,
        content: JsonValue = None,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        indent: int | None = None,
    ) -> None:
        encoded = json_encode(content, default=self.default_encoder, indent=indent)
        super().__init__(encoded, status_code, headers)

    @staticmethod
    def default_encoder(obj: object) -> object:
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        if isinstance(obj, uuid.UUID):
            return str(obj)
        # Delegate to model_dump() for JSON-safe Pydantic serialisation.
        if isinstance(obj, BaseModel):
            return obj.model_dump()
        # LazyFK wraps a raw FK id - serialise the underlying id value.
        fk_id = getattr(obj, "fk_id", MISSING_SENTINEL)
        if fk_id is not MISSING_SENTINEL:
            return str(fk_id) if fk_id is not None else None
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class HTMLResponse(Response):
    """HTML response with optional Jinja2 template rendering."""

    __slots__ = ()
    _MEDIA_TYPE = "text/html"

    def __init__(
        self,
        content: str | None = None,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        template: str | None = None,
        context: TemplateContext | None = None,
        template_dir: str | Path = "templates",
    ) -> None:
        if template and content is not None:
            raise ValueError("Cannot specify both 'content' and 'template'")

        if template:
            content = self.render_template(template, context or {}, template_dir)

        super().__init__(content, status_code, headers)

    def render_template(
        self, template: str, context: TemplateContext, template_dir: str | Path
    ) -> str:
        """Render a Jinja2 template; search paths cached by base_dir and installed apps."""
        # Block path traversal attempts in template names.
        if ".." in template or template.startswith("/") or template.startswith("\\"):
            raise ValueError(f"Invalid template name: {template!r}")
        # Block Windows-style absolute paths (e.g. C:\ or \\?\).
        if len(template) >= 2 and template[1] == ":" and template[0].isalpha():
            raise ValueError(f"Invalid template name: {template!r}")
        # Fall back to settings.TEMPLATES_DIR when the default sentinel is used.
        base_dir = template_dir
        if template_dir == "templates" and hasattr(settings, "TEMPLATES_DIR"):
            base_dir = cast("str | Path", settings.TEMPLATES_DIR)

        installed_apps = tuple(getattr(settings, "INSTALLED_APPS", ()))
        search_paths = compute_template_search_paths(str(base_dir), installed_apps)

        # Auto-inject the current request into template context when absent.
        if "request" not in context:
            try:
                req = current_request.get()
                if req is not None:
                    context = {**context, "request": req}
            except LookupError, ValueError:
                logger.debug(
                    "Failed to inject current request into template context", exc_info=True
                )

        env = get_jinja2_env_cached(search_paths)
        return cast("str", env.get_template(template).render(**context))


class PlainTextResponse(Response):
    """Plain text response."""

    __slots__ = ()
    _MEDIA_TYPE = "text/plain"


class RedirectResponse(Response):
    """HTTP redirect response (3xx)."""

    __slots__ = ()

    def __init__(
        self,
        url: str,
        status_code: int = 307,
        headers: dict[str, str] | None = None,
        **path_params: str,
    ) -> None:
        if NAMESPACED_ROUTE_RE.match(url):
            router = current_router.get()
            if router is not None:
                url = router.url_for(url, **path_params)
        if "\r" in url or "\n" in url:
            raise ValueError(f"Redirect URL must not contain CR or LF: {url!r}")
        # Block protocol-relative URLs that could redirect to external sites.
        stripped = url.lstrip()
        if stripped.startswith("//"):
            raise ValueError(f"Protocol-relative redirect URLs are not allowed: {url!r}")
        # Decode twice for security checks to catch double-encoded sequences.
        decoded = unquote(stripped)
        double_decoded = unquote(decoded)
        if (
            ".." in decoded
            or "/../" in decoded
            or ".." in double_decoded
            or "%2e" in stripped.lower()
            or "%2f" in stripped.lower()
            or "%5c" in stripped.lower()
            or "\\" in decoded
        ):
            raise ValueError(f"Redirect URL must not contain path traversal sequences: {url!r}")
        # Only allow http and https schemes in absolute redirect URLs.
        parsed = urlparse(decoded)
        if parsed.scheme and parsed.scheme not in ("http", "https", ""):
            raise ValueError(f"Redirect URL has disallowed scheme '{parsed.scheme}': {url!r}")
        if parsed.scheme:
            if "@" in parsed.netloc:
                raise ValueError(f"Redirect URL must not contain userinfo: {url!r}")
            redirect_host = unquote(parsed.hostname or "")
            allowed_redirect_hosts = tuple(
                getattr(settings, "ALLOWED_REDIRECT_HOSTS", getattr(settings, "ALLOWED_HOSTS", ()))
            )
            if not is_allowed_redirect_host(redirect_host, allowed_redirect_hosts):
                raise ValueError(f"Redirect URL host is not allowed: {url!r}")
        super().__init__(b"", status_code, {**(headers or {}), "location": url})


class StreamingResponse(Response):
    """Response with chunked body from an async generator or iterator."""

    __slots__ = ("_content_iterator",)

    def __init__(
        self,
        content: AsyncIterator[bytes] | Iterator[bytes] | Callable[[], AsyncIterator[bytes]],
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        media_type: str | None = None,
    ) -> None:
        self._content_iterator = content
        self.status_code = status_code
        self.media_type = media_type or "application/octet-stream"
        self._headers = MutableHeaders(raw=self.build_raw_headers(headers or {}))
        self.body = b""

    async def __call__(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self._headers.raw,
            }
        )
        iterator = self._content_iterator
        if callable(iterator):
            iterator = iterator()
        if hasattr(iterator, "__aiter__"):
            async for chunk in iterator:
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
        else:
            sync_iter = iter(iterator)

            def next_chunk() -> tuple[bytes | None, bool]:
                try:
                    return next(sync_iter), False
                except StopIteration:
                    return None, True

            while True:
                chunk, done = next_chunk()
                if done:
                    break
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})


class FileResponse(Response):
    """Serve a file from disk asynchronously with chunked streaming.

    Args:
        path: Filesystem path to serve.
        allowed_dir: If given, the resolved *path* must reside under this
            directory.  Prevents path-traversal when *path* contains
            user-supplied components.
    """

    __slots__ = ("file_path", "_filename")

    chunk_size: int = 65536

    def __init__(
        self,
        path: str,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        *,
        media_type: str | None = None,
        filename: str | None = None,
        allowed_dir: str | None = None,
    ) -> None:
        resolved = Path(path).resolve()
        if allowed_dir is not None:
            allowed = Path(allowed_dir).resolve()
            if not resolved.is_relative_to(allowed):
                raise ValueError(f"Path {path!r} is outside the allowed directory {allowed_dir!r}")
        self.file_path = str(resolved)
        self.status_code = status_code
        self.media_type = media_type or self.guess_media_type(path)
        self._filename = filename
        self._headers = MutableHeaders(raw=self.build_raw_headers(headers or {}))
        self.body = b""

    @staticmethod
    def guess_media_type(path: str) -> str:
        mt, _ = mimetypes.guess_type(path)
        return mt or "application/octet-stream"

    async def __call__(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        fstat = os.stat(self.file_path)
        file_size = fstat.st_size
        etag = f'"{int(fstat.st_mtime)}-{file_size}"'
        last_modified = email.utils.formatdate(fstat.st_mtime, usegmt=True)

        self._headers.set("etag", etag)
        self._headers.set("last-modified", last_modified)
        self._headers.set("accept-ranges", "bytes")

        if self._filename:
            # Sanitise filename to prevent content-disposition header injection.
            safe_name = self._filename.replace("\\", "\\\\").replace('"', '\\"')
            safe_name = safe_name.replace("\r", "").replace("\n", "")
            self._headers.set("content-disposition", f'attachment; filename="{safe_name}"')

        req_headers: dict[bytes, bytes] = dict(
            cast("list[tuple[bytes, bytes]]", scope.get("headers", []))
        )

        # Conditional request - If-None-Match (ETag).
        if_none_match = req_headers.get(b"if-none-match", b"").decode("latin-1").strip()
        if if_none_match and if_none_match in (etag, "*"):
            await send_complete_response(send, 304, self._headers.raw)
            return

        # Conditional request - If-Modified-Since.
        if_modified_since = req_headers.get(b"if-modified-since", b"").decode("latin-1").strip()
        if if_modified_since:
            try:
                ims_ts = email.utils.parsedate_to_datetime(if_modified_since).timestamp()
                if int(fstat.st_mtime) <= int(ims_ts):
                    await send_complete_response(send, 304, self._headers.raw)
                    return
            except TypeError, ValueError:
                pass

        # Range request - partial content (RFC 7233).
        range_header = req_headers.get(b"range", b"").decode("latin-1").strip()
        range_start: int = 0
        range_end: int = file_size - 1
        is_partial = False

        if range_header and range_header.startswith("bytes="):
            range_spec = range_header[6:]
            try:
                raw_start, raw_end = range_spec.split("-", 1)
                if raw_start == "":
                    # Suffix range - bytes=-N means last N bytes.
                    suffix = int(raw_end)
                    range_start = max(0, file_size - suffix)
                    range_end = file_size - 1
                else:
                    range_start = int(raw_start)
                    range_end = int(raw_end) if raw_end else file_size - 1
                if range_start > range_end or range_start >= file_size:
                    # Range Not Satisfiable - respond with 416.
                    self._headers.set("content-range", f"bytes */{file_size}")
                    await send_complete_response(send, 416, self._headers.raw)
                    return
                range_end = min(range_end, file_size - 1)
                is_partial = True
            except ValueError, IndexError:
                pass

        content_length = range_end - range_start + 1
        self._headers.set("content-length", str(content_length))

        if is_partial:
            self._headers.set("content-range", f"bytes {range_start}-{range_end}/{file_size}")
            status = 206
        else:
            status = self.status_code

        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": self._headers.raw,
            }
        )
        async with await anyio.open_file(self.file_path, "rb") as f:
            if range_start:
                await f.seek(range_start)
            remaining = content_length
            while remaining > 0:
                chunk = await f.read(min(self.chunk_size, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                more = remaining > 0
                await send({"type": "http.response.body", "body": chunk, "more_body": more})
            if remaining > 0:
                await send({"type": "http.response.body", "body": b"", "more_body": False})


class GZipResponse(Response):
    """Response with gzip-compressed body."""

    __slots__ = ("_inner", "_minimum_size", "_compresslevel")

    def __init__(self, content: Response, minimum_size: int = 500, compresslevel: int = 6) -> None:
        self._inner = content
        self._minimum_size = minimum_size
        self._compresslevel = compresslevel

    # Content types already compressed; skip re-compression.
    _SKIP_COMPRESS_TYPES: frozenset[str] = frozenset(
        {
            "image/jpeg",
            "image/png",
            "image/gif",
            "image/webp",
            "image/avif",
            "video/",
            "audio/",
            "application/zip",
            "application/gzip",
            "application/x-gzip",
            "application/pdf",
            "application/octet-stream",
        }
    )

    async def __call__(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        inner = self._inner
        body = inner.body

        # Skip compression for already-compressed content types or small bodies.
        content_type = (inner.media_type or "").lower()
        should_skip = any(ct in content_type for ct in self._SKIP_COMPRESS_TYPES)

        if isinstance(inner, (StreamingResponse, FileResponse)):
            # Collect the full streamed body by intercepting ASGI events.
            collected_parts: list[bytes] = []

            async def collecting_send(event: ASGIMessage) -> None:
                if event["type"] == "http.response.body":
                    part = cast("bytes", event.get("body", b""))
                    if part:
                        collected_parts.append(part)

            await inner(scope, receive, collecting_send)
            body = b"".join(collected_parts)

        if should_skip or len(body) < self._minimum_size:
            # Skip compression for small or pre-compressed bodies.
            inner._headers.set("content-length", str(len(body)))
            await send_complete_response(send, inner.status_code, inner._headers.raw, body)
            return

        body = gzip.compress(body, self._compresslevel)
        inner._headers.set("content-encoding", "gzip")
        inner._headers.set("vary", "Accept-Encoding")
        inner._headers.set("content-length", str(len(body)))
        await send_complete_response(send, inner.status_code, inner._headers.raw, body)
