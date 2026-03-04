"""Static file serving for OpenViper."""

from __future__ import annotations

import importlib.util
import mimetypes
import shutil
from pathlib import Path
from typing import Any

import aiofiles

from openviper.conf import settings
from openviper.core.app_resolver import AppResolver
from openviper.http.response import Response


class NotModifiedResponse(Response):
    status_code = 304

    # type: ignore[override]
    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
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
        self.directories: list[Path] = [Path(d) for d in (directories or ["static"])]

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "https"):
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "/")
        if not path.startswith(self.url_path + "/"):
            await self.app(scope, receive, send)
            return

        # Static asset request should not be served if not found or if the method is incorrect

        method: str = scope.get("method", "GET").upper()
        if method not in ("GET", "HEAD"):
            await self._send_response(send, 405, b"Method Not Allowed", "text/plain")
            return

        relative = path[len(self.url_path) + 1 :]
        # Security: reject path traversal attempts
        if ".." in relative.split("/"):
            await self._send_response(send, 400, b"Bad Request", "text/plain")
            return

        file_path = self._find_file(relative)
        if file_path is None:
            await self._send_response(send, 404, b"Not Found", "text/plain")
            return

        await self._serve_file(scope, send, file_path, method)

    def _find_file(self, relative: str) -> Path | None:
        for directory in self.directories:
            candidate = (directory / relative).resolve()
            # Ensure candidate is inside the directory (no traversal)
            try:
                candidate.relative_to(directory.resolve())
            except ValueError:
                continue
            if candidate.is_file():
                return candidate
        return None

    async def _serve_file(self, scope: dict, send: Any, path: Path, method: str) -> None:
        stat_result = path.stat()
        file_size = stat_result.st_size
        last_modified = stat_result.st_mtime
        mime_type, encoding = mimetypes.guess_type(str(path))
        if mime_type is None:
            mime_type = "application/octet-stream"

        # Check If-None-Match / If-Modified-Since (simple etag)
        etag = f'"{int(last_modified)}-{file_size}"'
        headers = [
            [b"content-type", mime_type.encode()],
            [b"content-length", str(file_size).encode()],
            [b"etag", etag.encode()],
            [b"accept-ranges", b"bytes"],
            [b"cache-control", b"public, max-age=3600"],
        ]
        if encoding:
            headers.append([b"content-encoding", encoding.encode()])

        headers_raw: list[list[bytes]] = scope.get("headers", [])
        incoming = {k.lower(): v for k, v in headers_raw}
        if incoming.get(b"if-none-match", b"") == etag.encode():
            await send({"type": "http.response.start", "status": 304, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return

        await send({"type": "http.response.start", "status": 200, "headers": headers})
        if method == "HEAD":
            await send({"type": "http.response.body", "body": b""})
            return

        async with aiofiles.open(str(path), "rb") as f:
            chunk_size = 65536
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                await send(
                    {
                        "type": "http.response.body",
                        "body": chunk,
                        "more_body": True,
                    }
                )
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


def _discover_app_static_dirs() -> list[Path]:
    """Discover ``static/`` directories in installed apps and openviper built-in apps.

    Iterates over ``settings.INSTALLED_APPS`` (plus ``openviper.admin``), resolves
    each app to its filesystem location, and returns the list of existing
    ``static/`` directories found.
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
        except (ImportError, ModuleNotFoundError, ValueError):
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
        except Exception:  # noqa: BLE001
            pass

    return static_dirs


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
    dest = Path(dest_dir).resolve()
    resolved_sources = [Path(s).resolve() for s in source_dirs]

    # Only wipe dest when it doesn't overlap with any source dir.
    dest_overlaps_source = any(
        dest == src or dest.is_relative_to(src) or src.is_relative_to(dest)
        for src in resolved_sources
        if src.exists()
    )
    if clear and dest.exists() and not dest_overlaps_source:
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
    for app_static in _discover_app_static_dirs():
        count += _copy_tree(app_static)

    # 2. Collect from project STATICFILES_DIRS (highest priority — overwrites).
    for source in source_dirs:
        src = Path(source)
        if src.is_dir():
            count += _copy_tree(src)

    return count
