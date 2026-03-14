"""HTTP Response classes for OpenViper."""

from __future__ import annotations

import asyncio
import datetime
import email.utils
import gzip
import importlib
import json
import mimetypes
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import aiofiles
import aiofiles.os
import orjson as _orjson

from openviper.conf import settings
from openviper.template.environment import get_jinja2_env
from openviper.utils.datastructures import MutableHeaders

_MISSING = object()  # sentinel for getattr default

try:
    from jinja2 import Environment, FileSystemLoader
except ImportError:
    Environment = None  # type: ignore[misc, assignment]
    FileSystemLoader = None  # type: ignore[misc, assignment]


# ---------------------------------------------------------------------------
# JSON encoding helper
# ---------------------------------------------------------------------------


def _json_encode(content: Any, *, default: Any, indent: int | None) -> bytes:
    """Serialize *content* to JSON bytes using orjson (C extension)."""
    option: int | None = None
    if indent == 2:
        option = _orjson.OPT_INDENT_2
    elif indent is not None:
        # orjson only supports indent=2; fall back for other values
        return json.dumps(content, default=default, indent=indent).encode("utf-8")
    return _orjson.dumps(content, default=default, option=option)


# ---------------------------------------------------------------------------
# Jinja2 environment accessor
# ---------------------------------------------------------------------------


@lru_cache(maxsize=32)
def _compute_template_search_paths(
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
        except (ImportError, AttributeError):
            continue
    return tuple(search_paths)


def _get_jinja2_env(search_paths: tuple[str, ...]) -> Any:
    """Return a cached Jinja2 :class:`Environment` keyed by *search_paths*.

    Delegates to :func:`openviper.template.environment.get_jinja2_env` which
    owns the LRU cache and invokes the plugin loader on first construction.
    The ``Environment`` guard here preserves the existing test-patch surface
    (``patch("openviper.http.response.Environment", None)``).
    """
    if Environment is None:
        raise ImportError("jinja2 is required for template rendering")

    return get_jinja2_env(search_paths)


def _cache_clear() -> None:
    """Clear the underlying LRU caches — mirrors ``lru_cache.cache_clear``."""
    get_jinja2_env.cache_clear()
    _compute_template_search_paths.cache_clear()


_get_jinja2_env.cache_clear = _cache_clear  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Base Response
# ---------------------------------------------------------------------------


class Response:
    """Base HTTP response.

    Args:
        content: Response body. Bytes, str, or None.
        status_code: HTTP status code (default 200).
        headers: Optional dict of headers to set.
        media_type: Content-Type MIME type.
    """

    __slots__ = ("status_code", "media_type", "_headers", "body")

    # Subclass-level default; overridden at instance level in __init__.
    _MEDIA_TYPE: str | None = None
    charset: str = "utf-8"

    def __init__(
        self,
        content: Any = None,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        media_type: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.media_type = media_type or type(self)._MEDIA_TYPE
        self._headers = MutableHeaders(raw=self._build_raw_headers(headers or {}))
        self.body = self._encode(content)

    # ── Internals ─────────────────────────────────────────────────────────

    def _encode(self, content: Any) -> bytes:
        if content is None:
            return b""
        if isinstance(content, bytes):
            return content
        if isinstance(content, str):
            return content.encode(self.charset)
        raise TypeError(f"Response content must be str or bytes, not {type(content).__name__}")

    def _build_raw_headers(self, extra: dict[str, str]) -> list[list[bytes]]:
        raw: list[list[bytes]] = []
        # Content-Type
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
        # Guard against header injection via cookie name or value.
        if "\r" in key or "\n" in key:
            raise ValueError(f"Cookie name must not contain CR or LF: {key!r}")
        if "\r" in value or "\n" in value:
            raise ValueError(f"Cookie value must not contain CR or LF: {value!r}")
        cookie = f"{key}={value}"
        if max_age is not None:
            cookie += f"; Max-Age={max_age}"
        if expires is not None:
            # Convert int timestamp to HTTP date format (RFC 2822)
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
        self._headers.append("set-cookie", cookie)

    def delete_cookie(self, key: str, path: str = "/", domain: str | None = None) -> None:
        self.set_cookie(key, "", max_age=0, path=path, domain=domain)

    # ── ASGI ──────────────────────────────────────────────────────────────

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:  # noqa: ARG002
        body = self.body
        if body:
            self._headers.set("content-length", str(len(body)))
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self._headers.raw,
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})


# ---------------------------------------------------------------------------
# Concrete response types
# ---------------------------------------------------------------------------


class JSONResponse(Response):
    """JSON response serialised with orjson."""

    __slots__ = ()
    _MEDIA_TYPE = "application/json"

    def __init__(
        self,
        content: Any = None,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        indent: int | None = None,
    ) -> None:
        encoded = _json_encode(content, default=self._default_encoder, indent=indent)
        super().__init__(encoded, status_code, headers)

    @staticmethod
    def _default_encoder(obj: Any) -> Any:
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        if isinstance(obj, uuid.UUID):
            return str(obj)
        # LazyFK wraps a raw FK id — serialize the underlying id value
        fk_id = getattr(obj, "fk_id", _MISSING)
        if fk_id is not _MISSING:
            return str(fk_id) if fk_id is not None else None
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class HTMLResponse(Response):
    """HTML response with optional Jinja2 template rendering."""

    __slots__ = ()
    _MEDIA_TYPE = "text/html"

    def __init__(
        self,
        content: Any = None,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        template: str | None = None,
        context: dict[str, Any] | None = None,
        template_dir: str | Path = "templates",
    ) -> None:
        if template and content is not None:
            raise ValueError("Cannot specify both 'content' and 'template'")

        if template:
            content = self._render_template(template, context or {}, template_dir)

        super().__init__(content, status_code, headers)

    def _render_template(
        self, template: str, context: dict[str, Any], template_dir: str | Path
    ) -> str:
        """Render a Jinja2 template; search paths cached by base_dir and installed apps."""
        # Block path traversal attempts in template names.
        if ".." in template or template.startswith("/") or template.startswith("\\"):
            raise ValueError(f"Invalid template name: {template!r}")
        # Use settings.TEMPLATES_DIR if template_dir is the default sentinel
        base_dir = template_dir
        if template_dir == "templates" and hasattr(settings, "TEMPLATES_DIR"):
            base_dir = settings.TEMPLATES_DIR

        installed_apps = tuple(getattr(settings, "INSTALLED_APPS", ()))
        search_paths = _compute_template_search_paths(str(base_dir), installed_apps)

        # Auto-inject the current request if not already in context
        if "request" not in context:
            try:
                from openviper.core.context import current_request

                req = current_request.get()
                if req is not None:
                    context = {**context, "request": req}
            except Exception:
                pass

        env = _get_jinja2_env(search_paths)
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
    ) -> None:
        if "\r" in url or "\n" in url:
            raise ValueError(f"Redirect URL must not contain CR or LF: {url!r}")
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
        self._headers = MutableHeaders(raw=self._build_raw_headers(headers or {}))
        self.body = b""  # Not used in streaming

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:  # noqa: ARG002
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
            # Offload sync iterator to thread pool to avoid blocking event loop
            sync_iter = iter(iterator)

            def _next() -> tuple[bytes | None, bool]:
                try:
                    return next(sync_iter), False
                except StopIteration:
                    return None, True

            while True:
                chunk, done = await asyncio.to_thread(_next)
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
            if not str(resolved).startswith(str(allowed) + "/") and resolved != allowed:
                raise ValueError(f"Path {path!r} is outside the allowed directory {allowed_dir!r}")
        self.file_path = str(resolved)
        self.status_code = status_code
        self.media_type = media_type or self._guess_media_type(path)
        self._filename = filename
        self._headers = MutableHeaders(raw=self._build_raw_headers(headers or {}))
        self.body = b""  # Streaming — not used by __call__

    @staticmethod
    def _guess_media_type(path: str) -> str:
        mt, _ = mimetypes.guess_type(path)
        return mt or "application/octet-stream"

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:  # noqa: ARG002
        # Async file stat to avoid blocking event loop
        fstat = await aiofiles.os.stat(self.file_path)
        etag = f'"{int(fstat.st_mtime)}-{fstat.st_size}"'
        last_modified = email.utils.formatdate(fstat.st_mtime, usegmt=True)

        self._headers.set("etag", etag)
        self._headers.set("last-modified", last_modified)

        if self._filename:
            # Sanitize filename to prevent content-disposition header injection.
            safe_name = self._filename.replace("\\", "\\\\").replace('"', '\\"')
            safe_name = safe_name.replace("\r", "").replace("\n", "")
            self._headers.set("content-disposition", f'attachment; filename="{safe_name}"')

        # Conditional request: If-None-Match
        req_headers: dict[bytes, bytes] = dict(scope.get("headers", []))
        if_none_match = req_headers.get(b"if-none-match", b"").decode("latin-1").strip()
        if if_none_match and if_none_match in (etag, "*"):
            await send({"type": "http.response.start", "status": 304, "headers": self._headers.raw})
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            return

        # Conditional request: If-Modified-Since
        if_modified_since = req_headers.get(b"if-modified-since", b"").decode("latin-1").strip()
        if if_modified_since:
            try:
                ims_ts = email.utils.parsedate_to_datetime(if_modified_since).timestamp()
                if int(fstat.st_mtime) <= int(ims_ts):
                    await send(
                        {"type": "http.response.start", "status": 304, "headers": self._headers.raw}
                    )
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
                    return
            except (TypeError, ValueError):
                pass  # Malformed date — serve the full response

        self._headers.set("content-length", str(fstat.st_size))
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self._headers.raw,
            }
        )
        async with aiofiles.open(self.file_path, "rb") as f:
            while True:
                chunk = await f.read(self.chunk_size)
                if not chunk:
                    break
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})


class GZipResponse(Response):
    """Response with gzip-compressed body."""

    __slots__ = ("_inner", "_minimum_size", "_compresslevel")

    def __init__(self, content: Response, minimum_size: int = 500, compresslevel: int = 6) -> None:
        self._inner = content
        self._minimum_size = minimum_size
        self._compresslevel = compresslevel
        # The inherited slots (status_code, media_type, _headers, body) are
        # intentionally left uninitialised; __call__ delegates to self._inner.

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        inner = self._inner
        body = inner.body
        if not body:
            # StreamingResponse / FileResponse — body is b""; delegate as-is.
            await inner(scope, receive, send)
            return
        if len(body) >= self._minimum_size:
            # Offload CPU-intensive compression to thread pool to avoid blocking event loop.
            body = await asyncio.to_thread(gzip.compress, body, self._compresslevel)
            inner._headers.set("content-encoding", "gzip")
            inner._headers.set("content-length", str(len(body)))
            inner._headers.set("vary", "Accept-Encoding")
        await send(
            {
                "type": "http.response.start",
                "status": inner.status_code,
                "headers": inner._headers.raw,
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})
