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

import os
import uuid
from pathlib import Path
from typing import Any

from openviper.conf import settings


class Storage:
    """Abstract base for all storage backends."""

    async def save(self, name: str, content: bytes | Any) -> str:
        """Save a file and return the final storage path (relative).

        Args:
            name: Desired file name / path (may be adjusted to avoid collisions).
            content: Raw bytes or a file-like object with a ``read()`` method.

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
        """Generate a collision-resistant file name by adding a UUID suffix."""
        base, ext = os.path.splitext(name)
        return f"{base}_{uuid.uuid4().hex[:8]}{ext}"


class FileSystemStorage(Storage):
    """Store files on the local filesystem.

    Args:
        location: Absolute or relative directory path for file storage.
                  Defaults to ``MEDIA_ROOT`` from settings.
        base_url: URL prefix for serving files.
                  Defaults to ``MEDIA_URL`` from settings.
    """

    def __init__(self, location: str | None = None, base_url: str | None = None) -> None:
        self._location = location
        self._base_url = base_url

    @property
    def location(self) -> str:
        if self._location is not None:
            return self._location
        # Lazy import to avoid circular dependency

        return getattr(settings, "MEDIA_ROOT", "./media/")

    @property
    def base_url(self) -> str:
        if self._base_url is not None:
            return self._base_url

        return getattr(settings, "MEDIA_URL", "/media/")

    def _full_path(self, name: str) -> Path:
        return Path(self.location) / name

    async def save(self, name: str, content: bytes | Any) -> str:
        full_path = self._full_path(name)

        # Ensure the target directory exists
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Avoid overwriting an existing file
        if full_path.exists():
            name = self._generate_unique_name(name)
            full_path = self._full_path(name)
            full_path.parent.mkdir(parents=True, exist_ok=True)

        # Read bytes from content
        if isinstance(content, bytes):
            data = content
        elif hasattr(content, "read"):
            data = content.read()
            if hasattr(data, "__await__"):
                data = await data
        else:
            data = bytes(content)

        full_path.write_bytes(data)
        return name

    async def delete(self, name: str) -> None:
        full_path = self._full_path(name)
        if full_path.exists():
            full_path.unlink()

    async def exists(self, name: str) -> bool:
        return self._full_path(name).exists()

    def url(self, name: str) -> str:
        base = self.base_url.rstrip("/")
        return f"{base}/{name}"

    async def size(self, name: str) -> int:
        return self._full_path(name).stat().st_size


class _DefaultStorage:
    """Lazy proxy that returns an appropriate storage backend based on settings."""

    _instance: Storage | None = None

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
