"""HTTP Request abstraction for OpenViper."""

from __future__ import annotations

import asyncio
import json
import urllib.parse
from collections.abc import AsyncIterator
from typing import Any

from openviper.utils.datastructures import Headers, ImmutableMultiDict, QueryParams


class UploadFile:
    """Represents an uploaded file from a multipart form submission."""

    __slots__ = ("filename", "content_type", "_file")

    def __init__(
        self,
        filename: str,
        content_type: str,
        file: Any,  # SpooledTemporaryFile or similar
    ) -> None:
        self.filename = filename
        self.content_type = content_type
        self._file = file

    async def read(self, size: int = -1) -> bytes:
        """Read bytes from the underlying (sync) SpooledTemporaryFile off-thread."""
        return await asyncio.to_thread(self._file.read, size)

    async def seek(self, offset: int) -> None:
        """Seek to *offset* in the underlying file off-thread."""
        await asyncio.to_thread(self._file.seek, offset)

    async def close(self) -> None:
        """Close the underlying file off-thread."""
        await asyncio.to_thread(self._file.close)

    def __repr__(self) -> str:
        return f"UploadFile(filename={self.filename!r}, content_type={self.content_type!r})"


class Request:
    """Encapsulates an HTTP request.

    This class wraps the raw ASGI scope and receive callable, providing
    convenient access to all request components: method, URL, headers,
    query parameters, path parameters, cookies, body, and JSON payload.

    Args:
        scope: ASGI connection scope dict.
        receive: ASGI receive callable.
    """

    __slots__ = (
        "_scope",
        "_receive",
        "_headers",
        "_headers_map",
        "_query_params",
        "_body",
        "_json",
        "_form",
        "_cookies",
        "path_params",
        "state",
        "user",
        "auth",
    )

    def __init__(self, scope: dict[str, Any], receive: Any = None) -> None:
        assert scope["type"] == "http", "Request must be HTTP scope"
        self._scope = scope
        self._receive = receive
        self._headers: Headers | None = None
        self._headers_map: dict[bytes, bytes] | None = None
        self._query_params: QueryParams | None = None
        self._body: bytes | None = None
        self._json: Any = None
        self._form: ImmutableMultiDict | None = None
        self._cookies: dict[str, str] | None = None
        self.path_params: dict[str, Any] = scope.get("path_params", {})
        self.state: dict[str, Any] = {}
        self.user: Any = None  # Set by AuthenticationMiddleware
        self.auth: Any = None  # Set by AuthenticationMiddleware

    # ── Basic properties ──────────────────────────────────────────────────

    @property
    def method(self) -> str:
        return self._scope["method"].upper()

    @property
    def url(self) -> URL:
        return URL(self._scope)

    @property
    def path(self) -> str:
        return self._scope.get("path", "/")

    @property
    def root_path(self) -> str:
        return self._scope.get("root_path", "")

    @property
    def headers(self) -> Headers:
        if self._headers is None:
            self._headers = Headers(raw=self._scope.get("headers", []))
        return self._headers

    @property
    def query_params(self) -> QueryParams:
        if self._query_params is None:
            qs = self._scope.get("query_string", b"").decode("latin-1")
            self._query_params = QueryParams(qs)
        return self._query_params

    @property
    def cookies(self) -> dict[str, str]:
        if self._cookies is None:
            self._cookies = {}
            cookie_header = self.headers.get("cookie", "")
            if cookie_header:
                for chunk in cookie_header.split(";"):
                    chunk = chunk.strip()
                    if "=" in chunk:
                        k, _, v = chunk.partition("=")
                        self._cookies[k.strip()] = v.strip()
        return self._cookies

    @property
    def client(self) -> tuple[str, int] | None:
        return self._scope.get("client")

    def header(self, name: bytes) -> bytes | None:
        """O(1) raw header lookup.

        Builds a ``bytes → bytes`` map from the ASGI scope headers on the
        first call and caches it for the lifetime of the request.  Header
        names are guaranteed to be lower-cased by the ASGI server.

        Args:
            name: Lower-cased header name (e.g. ``b"content-type"``).

        Returns:
            The raw header value, or ``None`` if the header is absent.
        """
        if self._headers_map is None:
            self._headers_map = {k.lower(): v for k, v in self._scope.get("headers", [])}
        return self._headers_map.get(name)

    # ── Body reading ──────────────────────────────────────────────────────

    async def body(self) -> bytes:
        """Read the full raw request body."""
        if self._body is None:
            chunks: list[bytes] = []
            while True:
                message = await self._receive()
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    break
            self._body = b"".join(chunks)
        return self._body

    async def json(self) -> Any:
        """Parse the request body as JSON."""
        if self._json is None:
            raw = await self.body()
            self._json = json.loads(raw)
        return self._json

    async def form(self) -> ImmutableMultiDict:
        """Parse application/x-www-form-urlencoded or multipart form data."""
        if self._form is None:
            content_type = self.headers.get("content-type", "")
            raw = await self.body()
            if "application/x-www-form-urlencoded" in content_type:
                parsed = urllib.parse.parse_qs(raw.decode("utf-8"), keep_blank_values=True)
                items = [(k, v) for k, vals in parsed.items() for v in vals]
                self._form = ImmutableMultiDict(items)
            else:
                # multipart — basic support
                self._form = ImmutableMultiDict([])
        return self._form

    async def stream(self) -> AsyncIterator[bytes]:
        """Iterate over the raw body in chunks."""
        if self._body is not None:
            yield self._body
            return
        while True:
            message = await self._receive()
            chunk = message.get("body", b"")
            if chunk:
                yield chunk
            if not message.get("more_body", False):
                break

    # ── Helpers ───────────────────────────────────────────────────────────

    def is_secure(self) -> bool:
        return self._scope.get("scheme", "http") in ("https", "wss")

    def __repr__(self) -> str:
        return f"<Request [{self.method}] {self.url}>"


class URL:
    """Parsed URL representation of an ASGI scope."""

    __slots__ = ("_scope", "_cached_str")

    def __init__(self, scope: dict[str, Any]) -> None:
        self._scope = scope
        self._cached_str: str | None = None

    @property
    def scheme(self) -> str:
        return self._scope.get("scheme", "http")

    @property
    def host(self) -> str:
        server = self._scope.get("server")
        if server:
            host, port = server
            if (self.scheme == "https" and port == 443) or (self.scheme == "http" and port == 80):
                return host
            return f"{host}:{port}"
        # Fall back to Host header
        for name, value in self._scope.get("headers", []):
            if name == b"host":
                return value.decode("latin-1")
        return "localhost"

    @property
    def path(self) -> str:
        return self._scope.get("path", "/")

    @property
    def query_string(self) -> str:
        return self._scope.get("query_string", b"").decode("latin-1")

    def __str__(self) -> str:
        if self._cached_str is None:
            url = f"{self.scheme}://{self.host}{self.path}"
            if self.query_string:
                url += f"?{self.query_string}"
            self._cached_str = url
        return self._cached_str

    def __repr__(self) -> str:
        return f"URL({str(self)!r})"
