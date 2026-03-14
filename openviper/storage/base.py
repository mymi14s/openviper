"""File storage backends for OpenViper.

Provides a pluggable storage API for handling uploaded files.  The default
:class:`FileSystemStorage` persists files to ``MEDIA_ROOT`` and serves them
at ``MEDIA_URL``.

Usage::

    from openviper.storage import default_storage

    # Save a file
    path = await default_storage.save("uploads/photo.jpg", content)

    # Get the public URL
    url = default_storage.url(path)

    # Delete a file
    await default_storage.delete(path)
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiofiles
import aiofiles.os

from openviper.conf import settings

# Characters that are unsafe in file names on common filesystems / shells.
_UNSAFE_FILENAME_RE = re.compile(r"[^\w\s.\-]")
# Maximum length for any single path component (e.g. FAT32 / ext4 limit).
_MAX_COMPONENT_LEN: int = 255


class Storage:
    """Abstract base for all storage backends."""

    # Default chunk size for streaming uploads (1 MB)
    CHUNK_SIZE: int = 1024 * 1024

    async def save(self, name: str, content: bytes | Any) -> str:
        """Save a file and return the final storage path (relative).

        Args:
            name: Desired file name / path (may be adjusted to avoid collisions).
            content: Raw bytes, a file-like object with a ``read()`` method,
                     or an async iterator yielding bytes.

        Returns:
            The relative path where the file was persisted.
        """
        raise NotImplementedError

    async def delete(self, name: str) -> None:
        """Delete the file at *name*.  No error if it does not exist."""
        raise NotImplementedError

    async def exists(self, name: str) -> bool:
        """Return ``True`` if a file already exists at *name*."""
        raise NotImplementedError

    def url(self, name: str) -> str:
        """Return the public URL for the file at *name*."""
        raise NotImplementedError

    async def size(self, name: str) -> int:
        """Return size in bytes of the file at *name*."""
        raise NotImplementedError

    def _generate_unique_name(self, name: str) -> str:
        """Generate a collision-resistant file name by adding a full UUID suffix."""
        base, ext = os.path.splitext(name)
        # Use a full 128-bit UUID hex (32 chars) rather than 8 chars.
        return f"{base}_{uuid.uuid4().hex}{ext}"


class FileSystemStorage(Storage):
    """Store files on the local filesystem with async I/O and memory-efficient streaming.

    Args:
        location: Absolute or relative directory path for file storage.
                  Defaults to ``MEDIA_ROOT`` from settings.
        base_url: URL prefix for serving files.
                  Defaults to ``MEDIA_URL`` from settings.
        chunk_size: Size of chunks for streaming uploads (default: 1 MB).
    """

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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _validate_name(self, name: str) -> str:
        """Validate and sanitise *name* against path traversal and bad filenames.

        - Rejects null bytes.
        - Normalises separators.
        - Removes ``..`` components (path traversal guard).
        - Truncates each component to ``_MAX_COMPONENT_LEN`` characters.
        - Returns the cleaned, relative POSIX-style path string.

        Raises:
            ValueError: if *name* is empty or contains null bytes.
        """
        if not name:
            raise ValueError("Storage name must not be empty.")
        if "\x00" in name:
            raise ValueError("Storage name must not contain null bytes.")

        # Normalise to POSIX separators and strip leading slash / dots.
        parts = Path(name.replace("\\", "/")).parts
        cleaned: list[str] = []
        for part in parts:
            # Skip drive roots, absolute slashes, and traversal components.
            if part in {"", ".", ".."}:
                continue
            if re.match(r"^[a-zA-Z]:\\?$", part) or part == "/":
                continue
            # Truncate excessively long components.
            if len(part) > _MAX_COMPONENT_LEN:
                base, ext = os.path.splitext(part)
                part = base[: _MAX_COMPONENT_LEN - len(ext)] + ext
            cleaned.append(part)

        if not cleaned:
            raise ValueError(f"Storage name {name!r} resolves to an empty path after sanitisation.")

        return "/".join(cleaned)

    def _full_path(self, name: str) -> Path:
        """Return absolute path, guaranteed to be inside ``location``.

        Raises:
            ValueError: if the resolved path escapes the storage root
                        (defense-in-depth after ``_validate_name``),
                        or if the path involves symlinks.
        """
        root = Path(self.location).resolve()
        full = (root / name).resolve()

        # Check for symlinks
        if full.is_symlink():
            raise ValueError(f"Path {name!r} is a symlink, which is not allowed.")

        # Check if any parent directory is a symlink
        for parent in full.parents:
            if parent == root:
                break
            if parent.is_symlink():
                raise ValueError(f"Path {name!r} contains a symlink in its path.")

        # Ensure the resolved path stays within the storage root.
        try:
            full.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Path {name!r} escapes the storage root {str(root)!r}.") from exc
        return full

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _mkdir_async(self, path: Path) -> None:
        """Create *path* directory (and parents) asynchronously if needed."""
        with contextlib.suppress(FileExistsError):
            await aiofiles.os.makedirs(path, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def save(self, name: str, content: bytes | Any) -> str:
        """Save file with async I/O and memory-efficient chunked uploads.

        Supports:
        - bytes: Written in chunks to avoid memory exhaustion.
        - File-like objects: Read and written in chunks (sync or async ``read``).
        - Async iterators: Streamed directly to disk.
        """
        name = self._validate_name(name)
        full_path = self._full_path(name)

        # Ensure the target directory exists.
        await self._mkdir_async(full_path.parent)

        # Avoid overwriting an existing file.
        if await aiofiles.os.path.exists(str(full_path)):
            name = self._validate_name(self._generate_unique_name(name))
            full_path = self._full_path(name)
            # Parent dir is the same or was already created above — makedirs
            # with exist_ok=True is cheap so we just call it once more.
            await self._mkdir_async(full_path.parent)

        async with aiofiles.open(str(full_path), "wb") as f:
            if isinstance(content, bytes):
                total = len(content)
                offset = 0
                while offset < total:
                    chunk = content[offset : offset + self.chunk_size]
                    await f.write(chunk)
                    offset += self.chunk_size
                    # Yield control periodically for large files (but not on
                    # the very first iteration where offset was just 0).
                    if offset > 0 and offset % (self.chunk_size * 10) == 0:
                        await asyncio.sleep(0)

            elif hasattr(content, "__aiter__"):
                # Async iterator — stream directly without per-chunk yields
                # (the awaits inside the iterator already yield the event loop).
                async for chunk in content:
                    await f.write(chunk if isinstance(chunk, bytes) else bytes(chunk))

            elif hasattr(content, "read"):
                # File-like object — support both sync and async read().
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
                # Fallback: convert to bytes and write.
                await f.write(bytes(content))

        # Set restrictive file permissions (owner: rw, group: r, others: none)
        with contextlib.suppress(Exception):
            os.chmod(full_path, 0o640)

        return name

    async def delete(self, name: str) -> None:
        """Delete file asynchronously."""
        full_path = self._full_path(self._validate_name(name))
        if await aiofiles.os.path.exists(str(full_path)):
            await aiofiles.os.remove(str(full_path))

    async def exists(self, name: str) -> bool:
        """Check if file exists asynchronously."""
        return await aiofiles.os.path.exists(str(self._full_path(self._validate_name(name))))

    def url(self, name: str) -> str:
        """Return the public URL, with each path segment percent-encoded."""
        base = self.base_url.rstrip("/")
        encoded = "/".join(quote(segment, safe="") for segment in name.split("/"))
        return f"{base}/{encoded}"

    async def size(self, name: str) -> int:
        """Get file size asynchronously."""
        stat_result = await aiofiles.os.stat(str(self._full_path(self._validate_name(name))))
        return stat_result.st_size


class _DefaultStorage:
    """Lazy proxy that returns an appropriate storage backend based on settings."""

    # Instance variable (not class variable) so that configure() on one proxy
    # does not pollute other _DefaultStorage instances.
    def __init__(self) -> None:
        self._instance: Storage | None = None

    def _get_storage(self) -> Storage:
        if self._instance is None:
            self._instance = FileSystemStorage()
        return self._instance

    def configure(self, storage: Storage) -> None:
        """Programmatically override the default storage backend."""
        self._instance = storage

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get_storage(), name)


default_storage = _DefaultStorage()
