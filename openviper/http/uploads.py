"""Uploaded file wrapper for OpenViper multipart form handling."""

from __future__ import annotations

import asyncio
from typing import Any


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
