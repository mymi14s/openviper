"""Temporary storage helpers for tests."""

from io import BytesIO
from pathlib import Path

from openviper.http.uploads import UploadFile


def uploaded_file(
    filename: str,
    content: bytes,
    content_type: str = "application/octet-stream",
) -> UploadFile:
    """Return an OpenViper upload object backed by in-memory bytes."""

    return UploadFile(filename=filename, content_type=content_type, file=BytesIO(content))


def assert_storage_path(root: Path, path: Path) -> None:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_root != resolved_path and resolved_root not in resolved_path.parents:
        raise AssertionError(f"Path {path} escaped test storage root {root}.")
