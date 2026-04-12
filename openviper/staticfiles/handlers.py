"""Static file serving for OpenViper."""

from __future__ import annotations

import email.utils
import functools
import importlib.util
import mimetypes
import shutil
import stat as stat_module
from pathlib import Path
from typing import Any, Literal

import aiofiles
import aiofiles.os

from openviper.conf import settings
from openviper.core.app_resolver import AppResolver
from openviper.http.response import Response


class _FileEntry:
    """Bundles a resolved file path with its pre-fetched stat result."""

    __slots__ = ("path", "stat_result")

    def __init__(self, path: Path, stat_result: Any) -> None:
        self.path = path
        self.stat_result = stat_result


class NotModifiedResponse(Response):
    status_code = 304

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 304,
                "headers": [[b"content-length", b"0"]],
            }
        )
        await send({"type": "http.response.body", "body": b""})


class StaticFilesMiddleware:
    """ASGI middleware that serves static files from the local filesystem.

    Whether this middleware is attached to the app is controlled externally
    (in ``app.py``) based on ``settings.DEBUG`` and whether ``static()`` /
    ``media()`` were called in ``routes.py``.  Once it *is* attached it always
    serves — there is no second ``DEBUG`` guard inside the middleware itself.

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
        app: Any,
        url_path: str = "/static",
        directories: list[str | Path] | None = None,
    ) -> None:
        self.app = app
        self.url_path = url_path.rstrip("/")
        # Pre-resolve directories once so _find_file never calls .resolve() per request.
        self._resolved_dirs: list[tuple[Path, Path]] = [
            (Path(d), Path(d).resolve()) for d in (directories or ["static"])
        ]

    @property
    def directories(self) -> list[Path]:
        """Unresolved directory paths (for backwards-compat introspection)."""
        return [raw for raw, _ in self._resolved_dirs]

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
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
        # Reject path traversal attempts using Path.parts for correctness.
        if ".." in Path(relative).parts:
            await self._send_response(send, 400, b"Bad Request", "text/plain")
            return

        entry = await self._find_file(relative)
        if entry is None:
            await self._send_response(send, 404, b"Not Found", "text/plain")
            return

        await self._serve_file(scope, receive, send, entry, method)

    async def _find_file(self, relative: str) -> _FileEntry | None:
        """Find a file and return a _FileEntry, performing a single stat syscall."""
        for raw_dir, resolved_dir in self._resolved_dirs:
            candidate = (raw_dir / relative).resolve()

            # Reject symlinks to prevent traversal attacks.
            if candidate.is_symlink():
                continue

            # Reject if any parent path component between candidate and the
            # serve root is itself a symlink — ensures the full resolved path
            # stays inside the expected directory tree.
            symlinked_parent = False
            try:
                for parent in candidate.parents:
                    if parent == resolved_dir:
                        break
                    if parent.is_symlink():
                        symlinked_parent = True
                        break
            except Exception:
                continue
            if symlinked_parent:
                continue

            # Ensure candidate is inside the directory (no traversal).
            try:
                candidate.relative_to(resolved_dir)
            except ValueError:
                continue
            # Single stat call — avoids isfile+stat TOCTOU and halves syscall count.
            try:
                st = await aiofiles.os.stat(str(candidate))
            except FileNotFoundError:
                continue
            if stat_module.S_ISREG(st.st_mode):
                return _FileEntry(candidate, st)
        return None

    async def _serve_file(
        self,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
        entry: _FileEntry,
        method: str,
    ) -> None:
        """Serve a static file with ETag, Last-Modified, Range, and HEAD support."""
        file_size = entry.stat_result.st_size
        last_modified = entry.stat_result.st_mtime
        path = entry.path
        mime_type, encoding = mimetypes.guess_type(str(path))
        if mime_type is None:
            mime_type = "application/octet-stream"

        etag = f'"{int(last_modified)}-{file_size}"'
        last_modified_str = email.utils.formatdate(last_modified, usegmt=True)

        headers_raw: list[list[bytes]] = scope.get("headers", [])
        incoming = {k.lower(): v for k, v in headers_raw}

        if incoming.get(b"if-none-match", b"") == etag.encode():
            await NotModifiedResponse()(scope, receive, send)
            return

        common_headers: list[list[bytes]] = [
            [b"content-type", mime_type.encode()],
            [b"etag", etag.encode()],
            [b"accept-ranges", b"bytes"],
            [b"cache-control", b"public, max-age=3600"],
            [b"x-content-type-options", b"nosniff"],
            [b"last-modified", last_modified_str.encode()],
        ]
        if encoding:
            common_headers.append([b"content-encoding", encoding.encode()])

        range_start: int | None = None
        range_end: int | None = None
        range_header = incoming.get(b"range", b"")
        if_range = incoming.get(b"if-range", b"")
        if range_header:
            if if_range and if_range != etag.encode():
                range_header = b""
            else:
                result = _parse_range(range_header, file_size)
                if result == "unsatisfiable":
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 416,
                            "headers": [
                                [b"content-range", f"bytes */{file_size}".encode()],
                                [b"content-length", b"0"],
                            ],
                        }
                    )
                    await send({"type": "http.response.body", "body": b""})
                    return
                if result != "ignore":
                    range_start, range_end = result

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

        await send({"type": "http.response.start", "status": status, "headers": response_headers})

        if method == "HEAD":
            await send({"type": "http.response.body", "body": b""})
            return

        chunk_size = 65536
        async with aiofiles.open(str(path), "rb") as f:
            if range_start is not None and range_end is not None:
                await f.seek(range_start)
                remaining = range_end - range_start + 1
                while remaining > 0:
                    chunk = await f.read(min(chunk_size, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    await send({"type": "http.response.body", "body": chunk, "more_body": True})
            else:
                while True:
                    chunk = await f.read(chunk_size)
                    if not chunk:
                        break
                    await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    @staticmethod
    async def _send_response(send: Any, status: int, body: bytes, content_type: str) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    [b"content-type", content_type.encode()],
                    [b"content-length", str(len(body)).encode()],
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def _parse_range(
    range_header: bytes,
    file_size: int,
) -> tuple[int, int] | Literal["ignore", "unsatisfiable"]:
    """Parse a bytes Range header and return byte offsets or a resolution sentinel.

    Returns:
        ``(start, end)`` — inclusive byte offsets for a satisfiable single range.
        ``"ignore"``       — multi-range, unknown unit, or parse error; serve 200.
        ``"unsatisfiable"`` — valid but start is at or beyond EOF; respond 416.
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

    if spec.endswith("-"):
        try:
            start = int(spec[:-1])
        except ValueError:
            return "ignore"
        if start >= file_size:
            return "unsatisfiable"
        end = file_size - 1
        return start, end

    parts = spec.split("-", 1)
    if len(parts) != 2:
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
def _discover_app_static_dirs() -> tuple[Path, ...]:
    """Discover ``static/`` directories in installed apps and openviper built-in apps.

    Iterates over ``settings.INSTALLED_APPS`` (plus ``openviper.admin``), resolves
    each app to its filesystem location, and returns the tuple of existing
    ``static/`` directories found.

    Results are cached since INSTALLED_APPS doesn't change at runtime.
    """

    static_dirs: list[Path] = []
    seen: set[Path] = set()
    installed_apps: list[str] = getattr(settings, "INSTALLED_APPS", [])

    # Always include openviper.admin so the built admin SPA is collected.
    all_apps = list(installed_apps)
    if "openviper.admin" not in all_apps:
        all_apps.append("openviper.admin")

    for app_name in all_apps:
        # Try importlib first (works for pip-installed and framework apps).
        try:
            spec = importlib.util.find_spec(app_name)
            if spec is not None and spec.origin is not None:
                app_dir = Path(spec.origin).parent
                static_dir = app_dir / "static"
                if static_dir.is_dir() and static_dir.resolve() not in seen:
                    static_dirs.append(static_dir)
                    seen.add(static_dir.resolve())
                continue
        except ImportError, ModuleNotFoundError, ValueError:
            pass

        # Fallback: use AppResolver for project-level apps.
        try:
            resolver = AppResolver()
            app_path, found = resolver.resolve_app(app_name)
            if found and app_path:
                static_dir = Path(app_path) / "static"
                if static_dir.is_dir() and static_dir.resolve() not in seen:
                    static_dirs.append(static_dir)
                    seen.add(static_dir.resolve())
        except ImportError, AttributeError, TypeError, OSError:
            pass

    return tuple(static_dirs)


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

    # Only wipe dest when it doesn't overlap with any source dir.
    dest_overlaps_source = any(
        dest == src or dest.is_relative_to(src) or src.is_relative_to(dest)
        for src in resolved_sources
        if src.exists()
    )
    if clear and dest_raw.exists() and not dest_overlaps_source:
        if dest_raw.is_symlink():
            raise ValueError(f"STATIC_ROOT {dest_raw} is a symlink; refusing to delete")
        shutil.rmtree(dest)

    dest.mkdir(parents=True, exist_ok=True)

    count = 0

    def _copy_tree(src_root: Path) -> int:
        """Copy every file under *src_root* into *dest*, preserving structure."""
        copied = 0
        for item in src_root.rglob("*"):
            if not item.is_file():
                continue
            relative = item.relative_to(src_root)
            target = dest / relative
            # Skip when source and destination are the same file.
            if item.resolve() == target.resolve():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(item), str(target))
            copied += 1
        return copied

    # 1. Collect from installed apps' static/ directories (lowest priority).
    for app_static in list(_discover_app_static_dirs()):
        count += _copy_tree(app_static)

    # 2. Collect from project STATICFILES_DIRS (highest priority — overwrites).
    for source in source_dirs:
        src = Path(source)
        if src.is_dir():
            count += _copy_tree(src)

    return count
