"""Uploaded file wrapper for OpenViper multipart form handling."""

from __future__ import annotations

import os
import re
from typing import IO

# Characters and patterns that are unsafe in filenames.
UNSAFE_FILENAME_RE = re.compile(r"[\\/\x00-\x1f\x7f]|(\.\.)")
MAX_COMPONENT_LEN = 255


def sanitize_filename(filename: str) -> str:
    """Strip path components, null bytes, and traversal sequences from *filename*.

    Returns a safe basename suitable for storage on the filesystem.
    """
    # Extract basename to discard any directory components supplied by the client.
    name = os.path.basename(filename.replace("\\", "/"))
    # Remove null bytes and control characters.
    name = UNSAFE_FILENAME_RE.sub("", name)
    # Truncate excessively long filenames.
    if len(name) > MAX_COMPONENT_LEN:
        name = name[:MAX_COMPONENT_LEN]
    # Fall back to a default if sanitisation emptied the name.
    if not name or name.startswith("."):
        name = "upload"
    return name


class UploadFile:
    """Represents an uploaded file from a multipart form submission."""

    __slots__ = ("filename", "content_type", "_file", "original_filename")

    def __init__(
        self,
        filename: str,
        content_type: str,
        file: IO[bytes],
    ) -> None:
        self.original_filename = filename
        self.filename = sanitize_filename(filename)
        self.content_type = content_type
        self._file = file

    async def read(self, size: int = -1) -> bytes:
        """Read bytes from the underlying file object."""
        return self._file.read(size)

    async def seek(self, offset: int) -> None:
        """Seek to *offset* in the underlying file."""
        self._file.seek(offset)

    async def close(self) -> None:
        """Close the underlying file."""
        self._file.close()

    def __repr__(self) -> str:
        return f"UploadFile(filename={self.filename!r}, content_type={self.content_type!r})"
