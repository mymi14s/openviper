"""HTTP Response classes for OpenViper."""

from __future__ import annotations

import datetime
import functools
import gzip
import importlib
import json
import mimetypes
import os
import stat
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any, cast

import aiofiles
import orjson as _orjson

from openviper.conf import settings
from openviper.utils.datastructures import MutableHeaders

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
# Cached Jinja2 environment factory
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=16)
def _get_jinja2_env(search_paths: tuple[str, ...]) -> Any:
    """Return a cached Jinja2 :class:`Environment` keyed by *search_paths*.

    The cache prevents a new ``Environment`` from being constructed on every
    ``HTMLResponse`` render — a significant overhead when templates are hot.
    """
    if Environment is None:
        raise ImportError("jinja2 is required for template rendering")
    return Environment(loader=FileSystemLoader(list(search_paths)))


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
        cookie = f"{key}={value}"
        if max_age is not None:
            cookie += f"; Max-Age={max_age}"
        if expires is not None:
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
        """Render a Jinja2 template; Jinja2 env is cached by search-path tuple."""
        # Use settings.TEMPLATES_DIR if template_dir is the default sentinel
        base_dir = template_dir
        if template_dir == "templates" and hasattr(settings, "TEMPLATES_DIR"):
            base_dir = settings.TEMPLATES_DIR

        search_paths: list[str] = [str(base_dir)]
        installed_apps = getattr(settings, "INSTALLED_APPS", ())
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

        env = _get_jinja2_env(tuple(search_paths))
        return cast(str, env.get_template(template).render(**context))


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
            for chunk in iterator:
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})


class FileResponse(Response):
    """Serve a file from disk asynchronously with chunked streaming."""

    __slots__ = ("file_path",)

    chunk_size: int = 65536

    def __init__(
        self,
        path: str,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        media_type: str | None = None,
        filename: str | None = None,
    ) -> None:
        self.file_path = path
        self.status_code = status_code
        self.media_type = media_type or self._guess_media_type(path)
        extra_headers = dict(headers or {})
        if filename:
            extra_headers["content-disposition"] = f'attachment; filename="{filename}"'
        fstat = os.stat(path)
        extra_headers["content-length"] = str(fstat[stat.ST_SIZE])
        extra_headers["last-modified"] = str(int(fstat[stat.ST_MTIME]))
        self._headers = MutableHeaders(raw=self._build_raw_headers(extra_headers))
        self.body = b""  # Streaming — not used by __call__

    @staticmethod
    def _guess_media_type(path: str) -> str:
        mt, _ = mimetypes.guess_type(path)
        return mt or "application/octet-stream"

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:  # noqa: ARG002
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

    def __init__(self, content: Response, minimum_size: int = 500, compresslevel: int = 9) -> None:
        self._inner = content
        self._minimum_size = minimum_size
        self._compresslevel = compresslevel
        # The inherited slots (status_code, media_type, _headers, body) are
        # intentionally left uninitialised; __call__ delegates to self._inner.

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        inner = self._inner
        body = inner.body
        if len(body) >= self._minimum_size:
            body = gzip.compress(body, compresslevel=self._compresslevel)
            inner._headers.set("content-encoding", "gzip")
            inner._headers.set("content-length", str(len(body)))
        await send(
            {
                "type": "http.response.start",
                "status": inner.status_code,
                "headers": inner._headers.raw,
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})
