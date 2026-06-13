"""HTTP Request abstraction for OpenViper."""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import logging
import re
import urllib.parse
from http.cookies import SimpleCookie
from typing import IO, TYPE_CHECKING, Any, cast

from openviper.exceptions import HTTPException
from openviper.http.uploads import UploadFile
from openviper.utils.datastructures import Headers, ImmutableMultiDict, QueryParams

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from types import ModuleType

    from openviper.auth.session.store import Session
    from openviper.http.types import (
        ASGIReceive,
        ASGIScope,
        JsonValue,
        MultipartField,
        MultipartFile,
        UserProtocol,
    )


def import_session_class() -> type[Session]:
    session_module = importlib.import_module("openviper.auth.session.store")
    return cast("type[Session]", session_module.Session)


multipart_module: ModuleType | None
try:
    multipart_module = importlib.import_module("python_multipart.multipart")
except ImportError:
    try:
        multipart_module = importlib.import_module("multipart.multipart")
    except ImportError:
        multipart_module = None

FormParser: Any = getattr(multipart_module, "FormParser", None)
parse_options_header: Any = getattr(multipart_module, "parse_options_header", None)

# Prevent unbounded memory allocation by capping request body size.
MAX_BODY_SIZE: int = 10 * 1024 * 1024

# Prevent DoS via excessive multipart file uploads.
MAX_FILES_PER_REQUEST: int = 100

# Reject Host header injection by validating hostname and port format.
VALID_HOST_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9.\-]*[A-Za-z0-9])?:(\d{1,5})$|^[A-Za-z0-9](?:[A-Za-z0-9.\-]*[A-Za-z0-9])?$"
)


def validate_host_port(raw: str) -> bool:
    """Return True if *raw* is a valid Host header value with an acceptable port."""
    match = VALID_HOST_RE.match(raw)
    if not match:
        return False
    port_str = match.group(1)
    if port_str is not None:
        port = int(port_str)
        if port < 1 or port > 65535:
            return False
    return True


def is_host_allowed(host: str) -> bool:
    """Return True when *host* is allowed by settings.ALLOWED_HOSTS.

    Supports exact hostnames, wildcard ``*``, and subdomain patterns
    starting with ``.``. Prevents Host header injection by rejecting
    any host not explicitly permitted by project settings.
    """
    from openviper.conf import settings

    allowed = getattr(settings, "ALLOWED_HOSTS", ())
    if not allowed:
        return True
    if "*" in allowed:
        return True
    host_lower = host.lower().split(":", 1)[0]
    for pattern in allowed:
        pattern = pattern.lower()
        if pattern == host_lower:
            return True
        if pattern.startswith(".") and (host_lower == pattern[1:] or host_lower.endswith(pattern)):
            return True
    return False


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

    def __init__(self, scope: ASGIScope, receive: ASGIReceive | None = None) -> None:
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
        self._json: JsonValue | None = None
        self._form: ImmutableMultiDict | None = None
        self._cookies: dict[str, str] | None = None
        self._url: URL | None = None
        self.path_params: dict[str, str] = cast("dict[str, str]", scope.get("path_params", {}))
        self.state: dict[str, object] = {}
        self.user: UserProtocol | None = None
        self.auth: object | None = None
        self._session: Session | None = None

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
            self._headers = Headers(
                raw=cast("list[tuple[bytes, bytes]]", self._scope.get("headers", []))
            )
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
                # Use stdlib SimpleCookie for efficient, standards-compliant parsing.
                cookie = SimpleCookie()
                cookie.load(cookie_header)
                self._cookies = {key: morsel.value for key, morsel in cookie.items()}
        return self._cookies

    @property
    def session(self) -> Session:
        """Lazy access to the session object.

        Requires SessionMiddleware to be active to populate _session.
        If not populated, checks the ASGI scope for an existing session.
        If still not found, returns an empty Session object with no store.
        """
        if self._session is None:
            if "session" in self._scope:
                self._session = cast("Session", self._scope["session"])
            else:
                self._session = import_session_class()(key="")
        return self._session

    @property
    def client(self) -> tuple[str, int] | None:
        result = self._scope.get("client")
        if result is None:
            return None
        return cast("tuple[str, int]", result)

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
            # ASGI spec guarantees headers are already lowercase.
            raw_headers = cast("list[tuple[bytes, bytes]]", self._scope.get("headers", []))
            self._headers_map = dict(raw_headers)
        return self._headers_map.get(name)

    async def body(self) -> bytes:
        """Read the full raw request body.

        Raises:
            ValueError: If the body exceeds MAX_BODY_SIZE or the actual body
                exceeds the declared Content-Length.
        """
        receive = self._receive
        if receive is None:
            raise RuntimeError("Request.receive not available")
        if self._body is None:
            content_length_header = self.header(b"content-length")
            content_length: int | None = None
            if content_length_header:
                with contextlib.suppress(ValueError, OverflowError):
                    content_length = int(content_length_header.decode("latin-1"))

            if content_length is not None:
                # Reject oversized declared Content-Length before allocating.
                if content_length > MAX_BODY_SIZE:
                    raise ValueError(
                        f"Request body too large: Content-Length {content_length} "
                        f"exceeds limit of {MAX_BODY_SIZE} bytes"
                    )
                # Pre-allocate for known size to avoid list growth/joins.
                buffer = bytearray(content_length)
                offset = 0
                while True:
                    message = await receive()
                    chunk = cast("bytes", message.get("body", b""))
                    if chunk:
                        chunk_len = len(chunk)
                        if offset + chunk_len > content_length:
                            raise ValueError(
                                f"Body ({offset + chunk_len} bytes) exceeds "
                                f"declared Content-Length ({content_length})"
                            )
                        buffer[offset : offset + chunk_len] = chunk
                        offset += chunk_len
                    if not cast("bool", message.get("more_body", False)):
                        break
                self._body = bytes(buffer[:offset])
            else:
                # Dynamic collection with size cap for unknown Content-Length.
                chunks: list[bytes] = []
                total = 0
                while True:
                    message = await receive()
                    chunk = cast("bytes", message.get("body", b""))
                    if chunk:
                        total += len(chunk)
                        if total > MAX_BODY_SIZE:
                            raise ValueError(
                                f"Request body exceeds maximum allowed size "
                                f"of {MAX_BODY_SIZE} bytes"
                            )
                        chunks.append(chunk)
                    if not cast("bool", message.get("more_body", False)):
                        break
                self._body = b"".join(chunks)
        return self._body

    async def json(self) -> JsonValue:
        """Parse the request body as JSON."""
        if self._json is None:
            raw = await self.body()
            try:
                self._json = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    400,
                    {
                        "message": "Malformed JSON body.",
                        "reason": exc.msg,
                        "line": exc.lineno,
                        "column": exc.colno,
                    },
                ) from exc
        return self._json

    async def form(self) -> ImmutableMultiDict:
        """Parse application/x-www-form-urlencoded or multipart form data."""
        if self._form is None:
            content_type: str = self.headers.get("content-type", "") or ""
            if "application/x-www-form-urlencoded" in content_type:
                raw = await self.body()
                parsed = urllib.parse.parse_qs(raw.decode("utf-8"), keep_blank_values=True)
                items: list[tuple[str, str | UploadFile]] = [
                    (k, v) for k, vals in parsed.items() for v in vals
                ]
                self._form = ImmutableMultiDict(items)
            elif "multipart/form-data" in content_type:
                if FormParser is None or parse_options_header is None:
                    raise ImportError(
                        "The 'python-multipart' package is required for multipart form "
                        "parsing. Install it with: pip install python-multipart"
                    )
                form_parser = FormParser
                parse_opts = parse_options_header
                form_items: list[tuple[str, str | UploadFile]] = []
                file_count = 0
                form_logger = logging.getLogger("openviper.form")

                def on_field(field: MultipartField) -> None:
                    if field.field_name is None:
                        return
                    # python-multipart routes file uploads without a
                    # Content-Disposition filename through on_field; detect
                    # binary data and treat as UploadFile.
                    raw_value = field.value
                    if raw_value is None:
                        form_items.append((field.field_name.decode(), ""))
                        return
                    try:
                        decoded = raw_value.decode("utf-8")
                        form_items.append((field.field_name.decode(), decoded))
                    except UnicodeDecodeError:
                        # Binary data without a filename header is still a file upload.
                        form_logger.warning(
                            "on_field binary fallback: name=%r len=%d",
                            field.field_name,
                            len(raw_value),
                        )
                        nonlocal file_count
                        file_count += 1
                        if file_count > MAX_FILES_PER_REQUEST:
                            raise ValueError(
                                f"Too many files in request. "
                                f"Maximum {MAX_FILES_PER_REQUEST} files allowed."
                            ) from None
                        # Infer MIME type from magic bytes when no header is present.
                        inferred_ct = "application/octet-stream"
                        if raw_value[:8] == b"\x89PNG\r\n\x1a\n":
                            inferred_ct = "image/png"
                        elif raw_value[:2] == b"\xff\xd8":
                            inferred_ct = "image/jpeg"
                        elif raw_value[:4] == b"RIFF" and raw_value[8:12] == b"WEBP":
                            inferred_ct = "image/webp"
                        elif raw_value[:6] in (b"GIF87a", b"GIF89a"):
                            inferred_ct = "image/gif"
                        ext_map = {
                            "image/png": ".png",
                            "image/jpeg": ".jpg",
                            "image/webp": ".webp",
                            "image/gif": ".gif",
                        }
                        ext = ext_map.get(inferred_ct, ".bin")
                        file_obj = io.BytesIO(raw_value)
                        upload = UploadFile(
                            filename=f"upload{ext}",
                            content_type=inferred_ct,
                            file=cast("IO[bytes]", file_obj),
                        )
                        form_items.append((field.field_name.decode(), upload))

                def on_file(file: MultipartFile) -> None:
                    nonlocal file_count
                    file_count += 1

                    # Enforce file count limit to prevent multipart DoS.
                    if file_count > MAX_FILES_PER_REQUEST:
                        raise ValueError(
                            f"Too many files in request. "
                            f"Maximum {MAX_FILES_PER_REQUEST} files allowed."
                        )

                    filename = file.file_name.decode() if file.file_name else "unknown"

                    # Capture actual Content-Type from multipart headers.
                    content_type_header = getattr(file, "content_type", None)
                    if content_type_header:
                        if isinstance(content_type_header, bytes):
                            file_content_type = content_type_header.decode("utf-8", errors="ignore")
                        else:
                            file_content_type = str(content_type_header)
                    else:
                        file_content_type = "application/octet-stream"

                    # Seek to beginning so the application can read the file.
                    if hasattr(file.file_object, "seek"):
                        file.file_object.seek(0)
                    upload = UploadFile(
                        filename=filename,
                        content_type=file_content_type,
                        file=cast("IO[bytes]", file.file_object),
                    )
                    # python-multipart may yield None field_name for some parts.
                    field_name = file.field_name.decode() if file.field_name else "file"
                    form_items.append((field_name, upload))

                ctype, options = parse_opts(content_type)
                boundary = options.get(b"boundary")

                if not boundary:
                    # Multipart without a boundary is malformed; return empty form.
                    self._form = ImmutableMultiDict([])
                    return self._form

                parser = form_parser(
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
        receive = self._receive
        if receive is None:
            raise RuntimeError("Request.receive not available")
        if self._body is not None:
            yield self._body
            return
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            chunk = cast("bytes", message.get("body", b""))
            if chunk:
                total += len(chunk)
                if total > MAX_BODY_SIZE:
                    raise ValueError(
                        f"Request body exceeds maximum allowed size of {MAX_BODY_SIZE} bytes"
                    )
                chunks.append(chunk)
                yield chunk
            if not cast("bool", message.get("more_body", False)):
                break
        self._body = b"".join(chunks)

    def is_secure(self) -> bool:
        return self._scope.get("scheme", "http") in ("https", "wss")

    def __repr__(self) -> str:
        return f"<Request [{self.method}] {self.url}>"


class URL:
    """Parsed URL representation of an ASGI scope."""

    __slots__ = ("_scope", "_cached_str")

    def __init__(self, scope: ASGIScope) -> None:
        self._scope = scope
        self._cached_str: str | None = None

    @property
    def scheme(self) -> str:
        return cast("str", self._scope.get("scheme", "http"))

    @property
    def host(self) -> str:
        server = self._scope.get("server")
        if server:
            host_val, port = cast("tuple[str, int]", server)
            if (self.scheme == "https" and port == 443) or (self.scheme == "http" and port == 80):
                return host_val
            return f"{host_val}:{port}"
        # Host header is untrusted; validate format and whitelist before use.
        for name, value in cast("list[tuple[bytes, bytes]]", self._scope.get("headers", [])):
            if name == b"host":
                raw = value.decode("latin-1")
                if validate_host_port(raw) and is_host_allowed(raw):
                    return raw
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
