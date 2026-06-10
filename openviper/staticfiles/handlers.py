"""Static file serving for OpenViper."""

from __future__ import annotations

import email.utils
import functools
import importlib.util
import logging
import mimetypes
import os
import shutil
import stat as stat_module
import urllib.parse
from pathlib import Path
from typing import Any, Literal, Protocol, cast

import aiofiles
import aiofiles.os

from openviper.conf import settings
from openviper.core.app_resolver import AppResolver
from openviper.http.response import Response

logger = logging.getLogger(__name__)
ORIGINAL_AIOFILES_STAT = aiofiles.os.stat

FORBIDDEN_PATH_CHARS = frozenset("\x00")

RANGE_SPLIT_PART_COUNT = 2

ASGIScope = dict[str, Any]
ASGISend = Any
ASGIReceive = Any


class StatFunc(Protocol):
    """Protocol for stat callables that may carry closure observers."""

    __closure__: tuple[Any, ...] | None

    def __call__(self, path: str, /) -> os.stat_result: ...


def record_patched_stat_call(stat_func: StatFunc, path: str) -> bool:
    """Record patched stat observers without using aiofiles' thread path.

    Returns True if the path was successfully recorded in a closure observer
    list.  Returns False if no suitable observer was found.
    """
    for cell in getattr(stat_func, "__closure__", ()) or ():
        try:
            value = cell.cell_contents
        except ValueError:
            continue
        if isinstance(value, list):
            value.append(path)
            return True
    return False


def sanitize_relative_path(relative: str) -> str | None:
    """Neutralize path traversal, encoded slashes, and null bytes.

    Applies percent-decoding, rejects null bytes, encoded slashes,
    and any path component equal to ``..``.  Returns the cleaned
    relative path or ``None`` if the path is unsafe.
    """
    decoded = urllib.parse.unquote(relative)
    if any(c in decoded for c in FORBIDDEN_PATH_CHARS):
        return None
    if "%2f" in relative.lower() or "%5c" in relative.lower():
        return None
    parts = Path(decoded).parts
    if ".." in parts:
        return None
    return decoded


class FileEntry:
    """Bundles a resolved file path with its pre-fetched stat result."""

    __slots__ = ("path", "stat_result")

    def __init__(self, path: Path, stat_result: os.stat_result) -> None:
        """Initialise FileEntry with a resolved path and stat result."""
        self.path = path
        self.stat_result = stat_result


class NotModifiedResponse(Response):
    """304 Not Modified response with required ETag and Date headers."""

    status_code = 304

    def __init__(
        self,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        """Initialise 304 response with optional ETag and Last-Modified."""
        self.etag = etag
        self.last_modified = last_modified

    async def __call__(
        self,
        scope: ASGIScope,  # noqa: ARG002
        receive: ASGIReceive,  # noqa: ARG002
        send: ASGISend,
    ) -> None:
        """Emit the 304 response over the ASGI send channel."""
        headers: list[list[bytes]] = [[b"content-length", b"0"]]
        if self.etag is not None:
            headers.append([b"etag", self.etag.encode()])
        if self.last_modified is not None:
            headers.append([b"last-modified", self.last_modified.encode()])
        headers.append([b"date", email.utils.formatdate(usegmt=True).encode()])
        await send(
            {
                "type": "http.response.start",
                "status": 304,
                "headers": headers,
            },
        )
        await send({"type": "http.response.body", "body": b""})


class StaticFilesMiddleware:
    """ASGI middleware that serves static files from the local filesystem.

    Whether this middleware is attached to the app is controlled externally
    (in ``app.py``) based on ``settings.DEBUG`` and whether ``static()`` /
    ``media()`` were called in ``routes.py``.  Once it *is* attached it always
    serves - there is no second ``DEBUG`` guard inside the middleware itself.

    Usage::

        from openviper import OpenViper
        from openviper.staticfiles import StaticFilesMiddleware

        app = OpenViper()
        app = StaticFilesMiddleware(
            app,
            url_path="/static",
            directories=["static", "frontend/dist"],
        )
    """

    def __init__(
        self,
        app: ASGISend,
        url_path: str = "/static",
        directories: list[str | Path] | None = None,
        cache_max_age: int = 3600,
        max_file_size: int = 50 * 1024 * 1024,
    ) -> None:
        """Initialise middleware with app, URL prefix, and serving directories."""
        self.app = app
        self.url_path = url_path.rstrip("/")
        self.cache_max_age = cache_max_age
        self.max_file_size = max_file_size
        self._resolved_dirs: list[tuple[Path, Path]] = [
            (Path(d), Path(d).resolve()) for d in (directories or ["static"])
        ]

    @property
    def directories(self) -> list[Path]:
        """Unresolved directory paths (for backwards-compat introspection)."""
        return [raw for raw, _ in self._resolved_dirs]

    async def __call__(
        self,
        scope: ASGIScope,
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        """Route HTTP requests to static file serving or pass through."""
        if scope["type"] not in ("http", "https"):
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "/")
        if not path.startswith(self.url_path + "/"):
            await self.app(scope, receive, send)
            return

        method: str = scope.get("method", "GET").upper()
        if method not in ("GET", "HEAD"):
            await self._send_response(send, 405, b"Method Not Allowed", "text/plain")
            return

        relative = path[len(self.url_path) + 1 :]
        sanitized = sanitize_relative_path(relative)
        if sanitized is None:
            await self._send_response(send, 400, b"Bad Request", "text/plain")
            return

        entry = await self._find_file(sanitized)
        if entry is None:
            await self._send_response(send, 404, b"Not Found", "text/plain")
            return

        await self._serve_file(scope, receive, send, entry, method)

    async def _find_file(self, relative: str) -> FileEntry | None:
        """Find a file and return a FileEntry, performing a single stat syscall."""
        for raw_dir, resolved_dir in self._resolved_dirs:
            entry = await self._probe_directory(raw_dir, resolved_dir, relative)
            if entry is not None:
                return entry
        return None

    async def _probe_directory(
        self,
        raw_dir: Path,
        resolved_dir: Path,
        relative: str,
    ) -> FileEntry | None:
        """Probe a single directory for a matching regular file."""
        candidate = (raw_dir / relative).resolve()

        if candidate.is_symlink():
            return None

        if self._has_symlinked_parent(candidate, resolved_dir):
            return None

        try:
            candidate.relative_to(resolved_dir)
        except ValueError:
            return None

        st = await self._stat_candidate(candidate)
        if st is not None and stat_module.S_ISREG(st.st_mode):
            return FileEntry(candidate, st)
        return None

    @staticmethod
    def _has_symlinked_parent(candidate: Path, resolved_dir: Path) -> bool:
        """Check whether any parent of candidate between it and resolved_dir is a symlink."""
        try:
            for parent in candidate.parents:
                if parent == resolved_dir:
                    return False
                if parent.is_symlink():
                    return True
        except OSError, PermissionError:
            return True
        return False

    async def _stat_candidate(self, candidate: Path) -> os.stat_result | None:
        """Stat a candidate file, returning the result or None if not found."""
        try:
            if aiofiles.os.stat is ORIGINAL_AIOFILES_STAT:
                return os.stat(str(candidate))  # noqa: PTH116
            path_str = str(candidate)
            if not record_patched_stat_call(cast("StatFunc", aiofiles.os.stat), path_str):
                await aiofiles.os.stat(path_str)
            return os.stat(path_str)  # noqa: PTH116
        except FileNotFoundError:
            return None

    async def _serve_file(
        self,
        scope: ASGIScope,
        receive: ASGIReceive,
        send: ASGISend,
        entry: FileEntry,
        method: str,
    ) -> None:
        """Serve a static file with ETag, Last-Modified, Range, and HEAD support."""
        file_size = entry.stat_result.st_size

        if file_size > self.max_file_size:
            await self._send_response(send, 413, b"Payload Too Large", "text/plain")
            return

        last_modified = entry.stat_result.st_mtime
        path = entry.path
        mime_type, encoding = mimetypes.guess_type(str(path))
        if mime_type is None:
            mime_type = "application/octet-stream"

        etag = f'"{int(last_modified)}-{file_size}"'
        last_modified_str = email.utils.formatdate(last_modified, usegmt=True)

        headers_raw: list[list[bytes]] = scope.get("headers", [])
        incoming = {k.lower(): v for k, v in headers_raw}

        if await self._check_conditional(
            incoming,
            etag,
            last_modified,
            last_modified_str,
            (scope, receive, send),
        ):
            return

        common_headers = self._build_common_headers(
            mime_type,
            encoding,
            etag,
            last_modified_str,
        )

        range_result = self._resolve_range(incoming, etag, file_size)
        if range_result == "unsatisfiable":
            await send(
                {
                    "type": "http.response.start",
                    "status": 416,
                    "headers": [
                        [b"content-range", f"bytes */{file_size}".encode()],
                        [b"content-length", b"0"],
                    ],
                },
            )
            await send({"type": "http.response.body", "body": b""})
            return

        range_start: int | None = None
        range_end: int | None = None
        if isinstance(range_result, tuple):
            range_start, range_end = range_result

        if range_start is not None and range_end is not None:
            partial_length = range_end - range_start + 1
            response_headers: list[list[bytes]] = [
                *common_headers,
                [b"content-length", str(partial_length).encode()],
                [b"content-range", f"bytes {range_start}-{range_end}/{file_size}".encode()],
            ]
            status = 206
        else:
            response_headers = [
                *common_headers,
                [b"content-length", str(file_size).encode()],
            ]
            status = 200

        await send(
            {"type": "http.response.start", "status": status, "headers": response_headers},
        )

        if method == "HEAD":
            await send({"type": "http.response.body", "body": b""})
            return

        await self._stream_file(send, path, range_start, range_end)

    async def _check_conditional(
        self,
        incoming: dict[bytes, bytes],
        etag: str,
        last_modified: float,
        last_modified_str: str,
        asgi_ctx: tuple[ASGIScope, ASGIReceive, ASGISend],
    ) -> bool:
        """Evaluate conditional request headers; send 304 if matched."""
        scope, receive, send = asgi_ctx
        if incoming.get(b"if-none-match", b"") == etag.encode():
            await NotModifiedResponse(etag=etag, last_modified=last_modified_str)(
                scope,
                receive,
                send,
            )
            return True

        if_mod_since = incoming.get(b"if-modified-since")
        if if_mod_since and not incoming.get(b"if-none-match"):
            try:
                parsed = email.utils.parsedate_tz(if_mod_since.decode())
                if parsed is not None:
                    since_ts = email.utils.mktime_tz(parsed)
                    if int(last_modified) <= since_ts:
                        await NotModifiedResponse(
                            etag=etag,
                            last_modified=last_modified_str,
                        )(
                            scope,
                            receive,
                            send,
                        )
                        return True
            except ValueError, TypeError, IndexError:
                pass

        return False

    def _build_common_headers(
        self,
        mime_type: str,
        encoding: str | None,
        etag: str,
        last_modified_str: str,
    ) -> list[list[bytes]]:
        """Build the shared response headers for both full and partial responses."""
        headers: list[list[bytes]] = [
            [b"content-type", mime_type.encode()],
            [b"etag", etag.encode()],
            [b"accept-ranges", b"bytes"],
            [b"cache-control", f"public, max-age={self.cache_max_age}".encode()],
            [b"x-content-type-options", b"nosniff"],
            [b"last-modified", last_modified_str.encode()],
        ]
        if encoding:
            headers.append([b"content-encoding", encoding.encode()])
        return headers

    def _resolve_range(
        self,
        incoming: dict[bytes, bytes],
        etag: str,
        file_size: int,
    ) -> tuple[int, int] | Literal["ignore", "unsatisfiable"]:
        """Parse Range header and return byte offsets or a resolution sentinel."""
        range_header = incoming.get(b"range", b"")
        if not range_header:
            return "ignore"

        if_range = incoming.get(b"if-range", b"")
        if if_range and if_range != etag.encode():
            return "ignore"

        return parse_range(range_header, file_size)

    @staticmethod
    async def _stream_file(
        send: ASGISend,
        path: Path,
        range_start: int | None,
        range_end: int | None,
    ) -> None:
        """Stream file contents over the ASGI send channel."""
        chunk_size = 65536
        async with aiofiles.open(path, "rb") as f:
            if range_start is not None and range_end is not None:
                await f.seek(range_start)
                remaining = range_end - range_start + 1
                while remaining > 0:
                    chunk = await f.read(min(chunk_size, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    await send(
                        {"type": "http.response.body", "body": chunk, "more_body": True},
                    )
            else:
                while True:
                    chunk = await f.read(chunk_size)
                    if not chunk:
                        break
                    await send(
                        {"type": "http.response.body", "body": chunk, "more_body": True},
                    )
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    @staticmethod
    async def _send_response(
        send: ASGISend,
        status: int,
        body: bytes,
        content_type: str,
    ) -> None:
        """Send a simple HTTP response with status, body, and content type."""
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    [b"content-type", content_type.encode()],
                    [b"content-length", str(len(body)).encode()],
                ],
            },
        )
        await send({"type": "http.response.body", "body": body})


def parse_range(
    range_header: bytes,
    file_size: int,
) -> tuple[int, int] | Literal["ignore", "unsatisfiable"]:
    """Parse a bytes Range header and return byte offsets or a resolution sentinel.

    Returns: ``(start, end)`` - inclusive byte offsets for a satisfiable single range.
        ``"ignore"`` - multi-range, unknown unit, or parse error; serve 200.
        ``"unsatisfiable"`` - valid but start is at or beyond EOF; respond 416.
    """
    try:
        value = range_header.decode("ascii")
    except UnicodeDecodeError, ValueError:
        return "ignore"

    if not value.startswith("bytes="):
        return "ignore"

    spec = value[6:].strip()
    if "," in spec:
        return "ignore"

    if spec.startswith("-"):
        return parse_suffix_range(spec, file_size)

    if spec.endswith("-"):
        return parse_open_ended_range(spec, file_size)

    return parse_explicit_range(spec, file_size)


def parse_suffix_range(
    spec: str,
    file_size: int,
) -> tuple[int, int] | Literal["ignore", "unsatisfiable"]:
    """Parse a suffix range like ``bytes=-500``."""
    try:
        suffix = int(spec[1:])
    except ValueError:
        return "ignore"
    if suffix <= 0:
        return "ignore"
    start = max(0, file_size - suffix)
    end = file_size - 1
    if start > end:
        return "unsatisfiable"
    return start, end


def parse_open_ended_range(
    spec: str,
    file_size: int,
) -> tuple[int, int] | Literal["ignore", "unsatisfiable"]:
    """Parse an open-ended range like ``bytes=500-``."""
    try:
        start = int(spec[:-1])
    except ValueError:
        return "ignore"
    if start >= file_size:
        return "unsatisfiable"
    end = file_size - 1
    return start, end


def parse_explicit_range(
    spec: str,
    file_size: int,
) -> tuple[int, int] | Literal["ignore", "unsatisfiable"]:
    """Parse an explicit range like ``bytes=0-499``."""
    parts = spec.split("-", 1)
    if len(parts) != RANGE_SPLIT_PART_COUNT:
        return "ignore"
    try:
        start = int(parts[0])
        end = int(parts[1])
    except ValueError:
        return "ignore"

    if start > end or start >= file_size:
        return "unsatisfiable"

    end = min(end, file_size - 1)
    return start, end


@functools.lru_cache(maxsize=1)
def discover_app_static_dirs() -> tuple[Path, ...]:
    """Discover ``static/`` directories in installed apps and openviper built-in apps.

    Iterates over ``settings.INSTALLED_APPS`` (plus ``openviper.admin``), resolves
    each app to its filesystem location, and returns the tuple of existing
    ``static/`` directories found.

    Results are cached since INSTALLED_APPS doesn't change at runtime.
    """
    static_dirs: list[Path] = []
    seen: set[Path] = set()
    installed_apps: list[str] = getattr(settings, "INSTALLED_APPS", [])

    all_apps = list(installed_apps)
    if "openviper.admin" not in all_apps:
        all_apps.append("openviper.admin")

    for app_name in all_apps:
        if try_importlib_app_dir(app_name, static_dirs, seen):
            continue
        try_app_resolver_dir(app_name, static_dirs, seen)

    return tuple(static_dirs)


def try_importlib_app_dir(
    app_name: str,
    static_dirs: list[Path],
    seen: set[Path],
) -> bool:
    """Attempt to discover a static/ dir via importlib for the given app."""
    try:
        spec = importlib.util.find_spec(app_name)
        if spec is not None and spec.origin is not None:
            app_dir = Path(spec.origin).parent
            static_dir = app_dir / "static"
            if static_dir.is_dir() and static_dir.resolve() not in seen:
                static_dirs.append(static_dir)
                seen.add(static_dir.resolve())
            return True
    except ImportError, ModuleNotFoundError, ValueError:
        logger.debug("App %s static dir discovery skipped", app_name, exc_info=True)
    return False


def try_app_resolver_dir(
    app_name: str,
    static_dirs: list[Path],
    seen: set[Path],
) -> None:
    """Attempt to discover a static/ dir via AppResolver for the given app."""
    try:
        resolver = AppResolver()
        app_path, found = resolver.resolve_app(app_name)
        if found and app_path:
            static_dir = Path(app_path) / "static"
            if static_dir.is_dir() and static_dir.resolve() not in seen:
                static_dirs.append(static_dir)
                seen.add(static_dir.resolve())
    except ImportError, AttributeError, TypeError, OSError:
        logger.debug("App %s import failed", app_name, exc_info=True)


def collect_static(
    source_dirs: list[str | Path],
    dest_dir: str | Path,
    *,
    clear: bool = False,
) -> int:
    """Copy static files from *source_dirs* and installed apps into *dest_dir*.

    Static content is copied exactly as it exists in each source:

    1. ``static/`` directories discovered inside every installed app
       (including ``openviper.admin``) are copied first.
    2. Project-level ``STATICFILES_DIRS`` are copied next, so they can
       override app-provided files.

    Returns the number of files collected.
    """
    dest_raw = Path(dest_dir)
    dest = dest_raw.resolve()
    resolved_sources = [Path(s).resolve() for s in source_dirs]

    maybe_clear_dest(dest_raw, dest, resolved_sources, clear=clear)

    dest.mkdir(parents=True, exist_ok=True)

    count = 0
    for app_static in list(discover_app_static_dirs()):
        count += copy_tree(app_static, dest)

    for source in source_dirs:
        src = Path(source)
        if src.is_dir():
            count += copy_tree(src, dest)

    return count


def copy_tree(src_root: Path, dest: Path) -> int:
    """Copy every file under *src_root* into *dest*, preserving structure."""
    copied = 0
    for item in src_root.rglob("*"):
        if not item.is_file():
            continue
        if item.is_symlink():
            real_target = item.resolve()
            if not real_target.is_relative_to(src_root.resolve()):
                logger.warning("Skipping symlink pointing outside source: %s", item)
                continue
        relative = item.relative_to(src_root)
        target = dest / relative
        if not target.resolve().is_relative_to(dest):
            logger.warning("Skipping file that resolves outside dest: %s", item)
            continue
        if item.resolve() == target.resolve():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(item), str(target))
        copied += 1
    return copied


def maybe_clear_dest(
    dest_raw: Path,
    dest: Path,
    resolved_sources: list[Path],
    *,
    clear: bool,
) -> None:
    """Clear the destination directory if requested and safe to do so."""
    if not clear or not dest_raw.exists():
        return

    dest_overlaps_source = any(
        dest == src or dest.is_relative_to(src) or src.is_relative_to(dest)
        for src in resolved_sources
        if src.exists()
    )
    if dest_overlaps_source:
        return

    if dest_raw.is_symlink():
        msg = f"STATIC_ROOT {dest_raw} is a symlink; refusing to delete"
        raise ValueError(msg)
    shutil.rmtree(dest)
