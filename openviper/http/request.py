"""HTTP Request abstraction for OpenViper."""

from __future__ import annotations

import contextlib
import json
import re
import urllib.parse
from collections.abc import AsyncIterator
from http.cookies import SimpleCookie
from typing import Any, cast

from openviper.http.uploads import UploadFile
from openviper.utils.datastructures import Headers, ImmutableMultiDict, QueryParams

try:
    from multipart.multipart import FormParser
    from multipart.multipart import parse_options_header as _parse_options_header
except ImportError:
    FormParser = None  # type: ignore[assignment,misc]
    _parse_options_header = None  # type: ignore[assignment]

# Maximum request body size (10 MB). Prevents unbounded memory allocation.
MAX_BODY_SIZE: int = 10 * 1024 * 1024

# Maximum number of files per multipart request (prevents DoS)
MAX_FILES_PER_REQUEST: int = 100

# Allow hostname chars + optional port; rejects Host header injection.
_VALID_HOST_RE = re.compile(r"^[A-Za-z0-9.\-]+(:\d{1,5})?$")


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
        "_url",
        "path_params",
        "state",
        "user",
        "auth",
        "_session",
    )

    def __init__(self, scope: dict[str, Any], receive: Any = None) -> None:
        if scope.get("type") not in ("http", "websocket"):
            raise TypeError(
                f"Request requires an HTTP or websocket scope, got {scope.get('type')!r}"
            )
        self._scope = scope
        self._receive = receive
        self._headers: Headers | None = None
        self._headers_map: dict[bytes, bytes] | None = None
        self._query_params: QueryParams | None = None
        self._body: bytes | None = None
        self._json: Any = None
        self._form: ImmutableMultiDict | None = None
        self._cookies: dict[str, str] | None = None
        self._url: URL | None = None
        self.path_params: dict[str, Any] = scope.get("path_params", {})
        self.state: dict[str, Any] = {}
        self.user: Any = None  # Set by AuthenticationMiddleware
        self.auth: Any = None  # Set by AuthenticationMiddleware
        self._session: Any = None  # Set by SessionMiddleware

    # ── Basic properties ──────────────────────────────────────────────────

    @property
    def method(self) -> str:
        return cast("str", self._scope["method"]).upper()

    @property
    def url(self) -> URL:
        if self._url is None:
            self._url = URL(self._scope)
        return self._url

    @property
    def path(self) -> str:
        return cast("str", self._scope.get("path", "/"))

    @property
    def root_path(self) -> str:
        return cast("str", self._scope.get("root_path", ""))

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
                # Use stdlib SimpleCookie for efficient, standards-compliant parsing
                cookie = SimpleCookie()
                cookie.load(cookie_header)
                self._cookies = {key: morsel.value for key, morsel in cookie.items()}
        return self._cookies

    @property
    def session(self) -> Any:
        """Lazy access to the session object.

        Requires SessionMiddleware to be active to populate _session.
        If not populated, checks the ASGI scope for an existing session.
        If still not found, returns an empty Session object with no store.
        """
        if self._session is None:
            # Check if session is already in the ASGI scope (from SessionMiddleware)
            if "session" in self._scope:
                self._session = self._scope["session"]
            else:
                # `auth.session.middleware` which imports `Request` from this
                # module — making a module-level import of Session circular.
                from openviper.auth.session.store import Session  # noqa: PLC0415

                self._session = Session(key="")
        return self._session

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
            # ASGI spec guarantees headers are already lowercase, no need for .lower()
            self._headers_map = dict(self._scope.get("headers", []))
        return self._headers_map.get(name)

    # ── Body reading ──────────────────────────────────────────────────────

    async def body(self) -> bytes:
        """Read the full raw request body.

        Raises:
            ValueError: If the body exceeds MAX_BODY_SIZE or the actual body
                exceeds the declared Content-Length.
        """
        if self._body is None:
            content_length_header = self.header(b"content-length")
            content_length: int | None = None
            if content_length_header:
                with contextlib.suppress(ValueError, OverflowError):
                    content_length = int(content_length_header.decode("latin-1"))

            if content_length is not None:
                # Reject oversized declared content-length before allocating.
                if content_length > MAX_BODY_SIZE:
                    raise ValueError(
                        f"Request body too large: Content-Length {content_length} "
                        f"exceeds limit of {MAX_BODY_SIZE} bytes"
                    )
                # Pre-allocate for known size to avoid list growth/joins.
                buffer = bytearray(content_length)
                offset = 0
                while True:
                    message = await self._receive()
                    chunk = message.get("body", b"")
                    if chunk:
                        chunk_len = len(chunk)
                        if offset + chunk_len > content_length:
                            raise ValueError(
                                f"Body ({offset + chunk_len} bytes) exceeds "
                                f"declared Content-Length ({content_length})"
                            )
                        buffer[offset : offset + chunk_len] = chunk
                        offset += chunk_len
                    if not message.get("more_body", False):
                        break
                self._body = bytes(buffer[:offset])
            else:
                # Dynamic collection with size cap.
                chunks: list[bytes] = []
                total = 0
                while True:
                    message = await self._receive()
                    chunk = message.get("body", b"")
                    if chunk:
                        total += len(chunk)
                        if total > MAX_BODY_SIZE:
                            raise ValueError(
                                f"Request body exceeds maximum allowed size "
                                f"of {MAX_BODY_SIZE} bytes"
                            )
                        chunks.append(chunk)
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
            content_type: str = self.headers.get("content-type", "") or ""
            if "application/x-www-form-urlencoded" in content_type:
                raw = await self.body()
                parsed = urllib.parse.parse_qs(raw.decode("utf-8"), keep_blank_values=True)
                items = [(k, v) for k, vals in parsed.items() for v in vals]
                self._form = ImmutableMultiDict(items)
            elif "multipart/form-data" in content_type:
                if FormParser is None or _parse_options_header is None:
                    raise ImportError(
                        "The 'python-multipart' package is required for multipart form "
                        "parsing. Install it with: pip install python-multipart"
                    )
                form_items: list[tuple[str, str | UploadFile]] = []
                file_count = 0  # Track file uploads

                def on_field(field: Any) -> None:
                    form_items.append((field.field_name.decode(), field.value.decode()))

                def on_file(file: Any) -> None:
                    nonlocal file_count
                    file_count += 1

                    # Enforce file count limit
                    if file_count > MAX_FILES_PER_REQUEST:
                        raise ValueError(
                            f"Too many files in request. "
                            f"Maximum {MAX_FILES_PER_REQUEST} files allowed."
                        )

                    filename = file.file_name.decode() if file.file_name else "unknown"

                    # Capture actual Content-Type from multipart headers
                    content_type_header = getattr(file, "content_type", None)
                    if content_type_header:
                        if isinstance(content_type_header, bytes):
                            file_content_type = content_type_header.decode("utf-8", errors="ignore")
                        else:
                            file_content_type = str(content_type_header)
                    else:
                        file_content_type = "application/octet-stream"

                    # Seek to beginning so it can be read by the application
                    if hasattr(file.file_object, "seek"):
                        file.file_object.seek(0)
                    upload = UploadFile(
                        filename=filename,
                        content_type=file_content_type,
                        file=file.file_object,
                    )
                    form_items.append((file.field_name.decode(), upload))

                ctype, options = _parse_options_header(content_type)
                boundary = options.get(b"boundary") or options.get("boundary")

                if not boundary:
                    self._form = ImmutableMultiDict([])
                    return self._form

                parser = FormParser(
                    ctype.decode() if isinstance(ctype, bytes) else ctype,
                    on_field=on_field,
                    on_file=on_file,
                    boundary=boundary,
                )
                async for chunk in self.stream():
                    if chunk:
                        parser.write(chunk)
                parser.finalize()

                self._form = ImmutableMultiDict(form_items)
            else:
                self._form = ImmutableMultiDict([])
        return self._form

    async def stream(self) -> AsyncIterator[bytes]:
        """Iterate over the raw body in chunks.

        Chunks are accumulated and cached so that a subsequent call to
        :meth:`body` still returns the full body even after streaming.

        Raises:
            ValueError: If the accumulated body exceeds MAX_BODY_SIZE.
        """
        if self._body is not None:
            yield self._body
            return
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await self._receive()
            chunk = message.get("body", b"")
            if chunk:
                total += len(chunk)
                if total > MAX_BODY_SIZE:
                    raise ValueError(
                        f"Request body exceeds maximum allowed size of {MAX_BODY_SIZE} bytes"
                    )
                chunks.append(chunk)
                yield chunk
            if not message.get("more_body", False):
                break
        self._body = b"".join(chunks)

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
        return cast("str", self._scope.get("scheme", "http"))

    @property
    def host(self) -> str:
        server = self._scope.get("server")
        if server:
            host, port = server
            if (self.scheme == "https" and port == 443) or (self.scheme == "http" and port == 80):
                return cast("str", host)
            return f"{host}:{port}"
        # Fall back to Host header — validate to prevent host header injection.
        for name, value in self._scope.get("headers", []):
            if name == b"host":
                raw = cast("bytes", value).decode("latin-1")
                if _VALID_HOST_RE.match(raw):
                    return raw
                # Reject malformed/injected Host header.
                return "localhost"
        return "localhost"

    @property
    def path(self) -> str:
        return cast("str", self._scope.get("path", "/"))

    @property
    def query_string(self) -> str:
        return cast("bytes", self._scope.get("query_string", b"")).decode("latin-1")

    def __str__(self) -> str:
        if self._cached_str is None:
            url = f"{self.scheme}://{self.host}{self.path}"
            if self.query_string:
                url += f"?{self.query_string}"
            self._cached_str = url
        return self._cached_str

    def __repr__(self) -> str:
        return f"URL({str(self)!r})"
