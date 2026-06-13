"""File storage backends for OpenViper.

Pluggable storage API for handling uploaded files.
:class:`FileSystemStorage` persists to ``MEDIA_ROOT``
and serves at ``MEDIA_URL``.
"""

from __future__ import annotations

import contextlib
import inspect
import os
import re
import threading
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import IO, Protocol, cast
from urllib.parse import quote

import aiofiles
import aiofiles.os

from openviper.conf import settings

UNSAFE_FILENAME_RE = re.compile(r"[^\w\s.\-]")
HIDDEN_FILENAME_RE = re.compile(r"^\.")
MAX_COMPONENT_LEN: int = 255
MAX_READ_SIZE: int = 100 * 1024 * 1024  # 100 MiB

type StorageContent = bytes | bytearray | AsyncIterator[bytes] | IO


class Storage(Protocol):
    """Protocol defining the interface for all storage backends."""

    CHUNK_SIZE: int

    async def save(self, name: str, content: StorageContent) -> str: ...
    async def delete(self, name: str) -> None: ...
    async def exists(self, name: str) -> bool: ...
    def url(self, name: str) -> str: ...
    async def size(self, name: str) -> int: ...
    async def read(self, name: str) -> bytes: ...
    async def listdir(self, path: str = "") -> list[str]: ...


def generate_unique_name(name: str) -> str:
    """Generate a collision-resistant name via UUID hex suffix."""
    base, ext = os.path.splitext(name)
    return f"{base}_{uuid.uuid4().hex}{ext}"


class FileSystemStorage:
    """Store files on the local filesystem with async I/O and streaming.

    Args:
        location: Directory path for file storage.
                  Defaults to ``MEDIA_ROOT`` from settings.
        base_url: URL prefix for serving files.
                  Defaults to ``MEDIA_URL`` from settings.
        chunk_size: Chunk size for streaming uploads (default: 1 MiB).
    """

    CHUNK_SIZE: int = 1024 * 1024  # 1 MiB

    def __init__(
        self,
        location: str | None = None,
        base_url: str | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> None:
        self._location = location
        self._base_url = base_url
        self.chunk_size = chunk_size

    @property
    def location(self) -> str:
        if self._location is not None:
            return self._location
        return getattr(settings, "MEDIA_ROOT", "./media/")

    @property
    def base_url(self) -> str:
        if self._base_url is not None:
            return self._base_url
        return getattr(settings, "MEDIA_URL", "/media/")

    def validate_name(self, name: str) -> str:
        """Validate and sanitise *name* against path traversal.

        - Rejects null bytes.
        - Replaces hidden filenames (leading dot).
        - Normalises separators.
        - Removes ``..`` components (path traversal guard).
        - Truncates each component to ``MAX_COMPONENT_LEN``.

        Raises:
            ValueError: if *name* is empty, contains null bytes,
                        or resolves to an empty path after sanitisation.
        """
        if not name:
            raise ValueError("Storage name must not be empty.")
        if "\x00" in name:
            raise ValueError("Storage name must not contain null bytes.")

        parts = Path(name.replace("\\", "/")).parts
        cleaned: list[str] = []
        for part in parts:
            # Prevent drive-root and traversal components.
            if part in {"", ".", ".."}:
                continue
            if re.match(r"^[a-zA-Z]:\\?$", part) or part == "/":
                continue
            # Prevent serving server config files (.htaccess, .env).
            if HIDDEN_FILENAME_RE.match(part):
                part = "_" + part[1:]
            part = UNSAFE_FILENAME_RE.sub("_", part)
            if len(part) > MAX_COMPONENT_LEN:
                base, ext = os.path.splitext(part)
                part = base[: MAX_COMPONENT_LEN - len(ext)] + ext
            cleaned.append(part)

        if not cleaned:
            raise ValueError(f"Storage name {name!r} resolves to an empty path after sanitisation.")

        return "/".join(cleaned)

    def full_path(self, name: str) -> Path:
        """Return absolute path, guaranteed to be inside ``location``.

        Performs symlink detection and path containment verification to
        prevent directory traversal attacks.  Containment is checked
        *before* symlink inspection so that escape attempts are rejected
        regardless of symlink state.

        Raises:
            ValueError: if the resolved path escapes the storage root,
                        or if the path involves symlinks.
        """
        root = Path(self.location).resolve()
        full = (root / name).resolve()

        # Containment check prevents directory traversal escapes.
        try:
            full.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Path {name!r} escapes the storage root {str(root)!r}.") from exc

        # Symlink check prevents indirect traversal via links.
        if full.is_symlink():
            raise ValueError(f"Path {name!r} is a symlink, which is not allowed.")
        for parent in full.parents:
            if parent == root:
                break
            if parent.is_symlink():
                raise ValueError(f"Path {name!r} contains a symlink in its path.")

        return full

    async def mkdir_async(self, path: Path) -> None:
        """Create *path* directory (and parents) asynchronously."""
        with contextlib.suppress(FileExistsError):
            await aiofiles.os.makedirs(str(path), exist_ok=True)

    def resolved_path(self, name: str) -> Path:
        """Validate *name* and return its absolute path inside ``location``.

        Combines :meth:`validate_name` and :meth:`full_path` into a
        single call so callers do not repeat the two-step dance.
        """
        return self.full_path(self.validate_name(name))

    async def save(self, name: str, content: StorageContent) -> str:
        """Save file with async I/O and chunked uploads.

        Uses an atomic write pattern (temp file + rename) to
        prevent partial writes.  Re-verifies path containment
        after temp file creation to mitigate TOCTOU.
        """
        name = self.validate_name(name)
        full_path = self.full_path(name)

        await self.mkdir_async(full_path.parent)

        # Avoid overwriting existing files by generating a unique name.
        if await self.exists(name):
            name = self.validate_name(generate_unique_name(name))
            full_path = self.full_path(name)
            await self.mkdir_async(full_path.parent)

        # Atomic write prevents partial-file corruption.
        # Use a UUID-based temp suffix to prevent predictability.
        tmp_suffix = f".tmp_{uuid.uuid4().hex[:8]}"
        tmp_path = full_path.with_suffix(full_path.suffix + tmp_suffix)
        try:
            async with aiofiles.open(str(tmp_path), "wb") as f:
                if isinstance(content, (bytes, bytearray)):
                    total = len(content)
                    offset = 0
                    while offset < total:
                        chunk = content[offset : offset + self.chunk_size]
                        await f.write(chunk)
                        offset += self.chunk_size
                elif hasattr(content, "__aiter__"):
                    async for chunk in content:
                        await f.write(chunk if isinstance(chunk, bytes) else bytes(chunk))
                elif hasattr(content, "read"):
                    while True:
                        if inspect.iscoroutinefunction(content.read):
                            chunk = await content.read(self.chunk_size)
                        else:
                            chunk = content.read(self.chunk_size)
                        if not chunk:
                            break
                        if not isinstance(chunk, bytes):
                            chunk = bytes(chunk)
                        await f.write(chunk)
                else:
                    await f.write(bytes(content))

            # Restrict permissions before the file is visible.
            with contextlib.suppress(OSError, PermissionError):
                os.chmod(str(tmp_path), 0o640)

            # Re-verify containment after temp write to mitigate TOCTOU.
            resolved_tmp = Path(str(tmp_path)).resolve()
            root = Path(self.location).resolve()
            try:
                resolved_tmp.relative_to(root)
            except ValueError:
                # Clean up temp file.
                with contextlib.suppress(OSError):
                    os.remove(str(tmp_path))
                raise ValueError(f"Temp file {str(tmp_path)!r} escapes the storage root.") from None

            os.replace(str(tmp_path), str(full_path))
        except BaseException:
            with contextlib.suppress(OSError):
                os.remove(str(tmp_path))
            raise

        return name

    async def delete(self, name: str) -> None:
        """Delete file asynchronously. No error if it does not exist."""
        full_path = self.resolved_path(name)
        with contextlib.suppress(FileNotFoundError):
            await aiofiles.os.remove(str(full_path))

    async def exists(self, name: str) -> bool:
        """Check if file exists asynchronously."""
        try:
            await aiofiles.os.stat(str(self.resolved_path(name)))
        except FileNotFoundError:
            return False
        return True

    def url(self, name: str) -> str:
        """Return the public URL with percent-encoded path segments."""
        validated = self.validate_name(name)
        base = self.base_url.rstrip("/")
        encoded = "/".join(quote(segment, safe="") for segment in validated.split("/"))
        return f"{base}/{encoded}"

    async def size(self, name: str) -> int:
        """Get file size asynchronously."""
        try:
            stat_result = await aiofiles.os.stat(str(self.resolved_path(name)))
        except FileNotFoundError:
            raise FileNotFoundError(f"File '{name}' does not exist in storage.") from None
        return cast("int", stat_result.st_size)

    async def read(self, name: str) -> bytes:
        """Read and return the full content of the file at *name*.

        Raises:
            ValueError: if the file exceeds ``MAX_READ_SIZE`` bytes.
        """
        full_path = self.resolved_path(name)
        file_size = (await aiofiles.os.stat(str(full_path))).st_size
        if file_size > MAX_READ_SIZE:
            raise ValueError(
                f"File '{name}' is {file_size} bytes, exceeding the "
                f"maximum read size of {MAX_READ_SIZE} bytes."
            )
        async with aiofiles.open(str(full_path), "rb") as f:
            return cast("bytes", await f.read())

    async def listdir(self, path: str = "") -> list[str]:
        """List entries under *path* in storage."""
        full_path = self.resolved_path(path) if path else Path(self.location)
        if not os.path.isdir(str(full_path)):
            return []
        return os.listdir(str(full_path))


class DefaultStorage:
    """Thread-safe lazy proxy for the default storage backend."""

    def __init__(self) -> None:
        self._instance: FileSystemStorage | None = None
        self._lock: threading.Lock = threading.Lock()

    def get_storage(self) -> FileSystemStorage:
        if self._instance is not None:
            return self._instance
        with self._lock:
            # Double-checked locking pattern for thread safety.
            if self._instance is None:
                self._instance = FileSystemStorage()
            return self._instance

    def configure(self, storage: FileSystemStorage) -> None:
        """Programmatically override the default storage backend."""
        with self._lock:
            self._instance = storage

    async def save(self, name: str, content: StorageContent) -> str:
        return await self.get_storage().save(name, content)

    async def delete(self, name: str) -> None:
        await self.get_storage().delete(name)

    async def exists(self, name: str) -> bool:
        return await self.get_storage().exists(name)

    def url(self, name: str) -> str:
        return self.get_storage().url(name)

    async def size(self, name: str) -> int:
        return await self.get_storage().size(name)

    async def read(self, name: str) -> bytes:
        return await self.get_storage().read(name)

    async def listdir(self, path: str = "") -> list[str]:
        return await self.get_storage().listdir(path)


default_storage = DefaultStorage()
