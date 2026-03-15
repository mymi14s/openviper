"""Attachment resolution helpers for OpenViper email delivery."""

from __future__ import annotations

import asyncio
import base64
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen


@dataclass(slots=True)
class AttachmentData:
    """Normalized attachment payload."""

    filename: str
    content: bytes
    mimetype: str = "application/octet-stream"


def attachment_to_payload(attachment: AttachmentData) -> dict[str, str]:
    """Serialize an attachment for background task transport."""
    return {
        "filename": attachment.filename,
        "content_b64": base64.b64encode(attachment.content).decode("ascii"),
        "mimetype": attachment.mimetype,
    }


def attachment_from_payload(payload: dict[str, str]) -> AttachmentData:
    """Deserialize an attachment payload from a background task."""
    return AttachmentData(
        filename=payload["filename"],
        content=base64.b64decode(payload["content_b64"].encode("ascii")),
        mimetype=payload.get("mimetype") or "application/octet-stream",
    )


async def resolve_attachments(attachments: list[Any] | None) -> list[AttachmentData]:
    """Resolve arbitrary attachment inputs into :class:`AttachmentData`."""
    if not attachments:
        return []
    tasks = [
        _resolve_attachment(attachment, index)
        for index, attachment in enumerate(attachments, start=1)
    ]
    return list(await asyncio.gather(*tasks))


async def _resolve_attachment(item: Any, index: int) -> AttachmentData:
    if isinstance(item, AttachmentData):
        return item

    if isinstance(item, dict):
        return await _resolve_dict_attachment(item, index)

    if isinstance(item, tuple):
        return await _resolve_tuple_attachment(item, index)

    if isinstance(item, (bytes, bytearray)):
        return AttachmentData(
            filename=f"attachment-{index}.bin",
            content=bytes(item),
            mimetype="application/octet-stream",
        )

    if isinstance(item, Path):
        return await _resolve_file_attachment(item, item.name)

    if isinstance(item, str):
        parsed = urlparse(item)
        if parsed.scheme in {"http", "https"}:
            return await _resolve_url_attachment(item, index)
        return await _resolve_file_attachment(Path(item), Path(item).name)

    raise TypeError(f"Unsupported attachment type: {type(item).__name__}")


async def _resolve_dict_attachment(item: dict[str, Any], index: int) -> AttachmentData:
    if "content_b64" in item:
        return attachment_from_payload(
            {
                "filename": str(item.get("filename") or f"attachment-{index}.bin"),
                "content_b64": str(item["content_b64"]),
                "mimetype": str(item.get("mimetype") or "application/octet-stream"),
            }
        )

    if "path" in item:
        attachment = await _resolve_file_attachment(
            Path(str(item["path"])),
            str(item.get("filename") or Path(str(item["path"])).name),
        )
        if item.get("mimetype"):
            attachment.mimetype = str(item["mimetype"])
        return attachment

    if "url" in item:
        attachment = await _resolve_url_attachment(str(item["url"]), index)
        if item.get("filename"):
            attachment.filename = str(item["filename"])
        if item.get("mimetype"):
            attachment.mimetype = str(item["mimetype"])
        return attachment

    if "content" in item:
        filename = str(item.get("filename") or f"attachment-{index}.bin")
        content = item["content"]
        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        elif isinstance(content, (bytes, bytearray)):
            content_bytes = bytes(content)
        else:
            raise TypeError("Attachment 'content' must be bytes or str.")
        return AttachmentData(
            filename=filename,
            content=content_bytes,
            mimetype=_guess_mimetype(filename, item.get("mimetype")),
        )

    raise TypeError("Attachment dict must include one of: path, url, content, content_b64.")


async def _resolve_tuple_attachment(item: tuple[Any, ...], index: int) -> AttachmentData:
    if len(item) not in {2, 3}:
        raise TypeError(
            "Attachment tuple must be (filename, content) or (filename, content, mimetype)."
        )

    filename = str(item[0])
    payload = item[1]
    mimetype = item[2] if len(item) == 3 else None

    if isinstance(payload, (bytes, bytearray)):
        return AttachmentData(
            filename=filename,
            content=bytes(payload),
            mimetype=_guess_mimetype(filename, mimetype),
        )

    if isinstance(payload, Path):
        return await _resolve_file_attachment(payload, filename)

    if isinstance(payload, str):
        parsed = urlparse(payload)
        if parsed.scheme in {"http", "https"}:
            attachment = await _resolve_url_attachment(payload, index)
            attachment.filename = filename
            attachment.mimetype = _guess_mimetype(filename, mimetype or attachment.mimetype)
            return attachment

        file_path = Path(payload)
        if file_path.exists():
            return await _resolve_file_attachment(file_path, filename)

        return AttachmentData(
            filename=filename,
            content=payload.encode("utf-8"),
            mimetype=_guess_mimetype(filename, mimetype),
        )

    raise TypeError("Unsupported attachment tuple payload type.")


async def _resolve_file_attachment(path: Path, filename: str) -> AttachmentData:
    content = await asyncio.to_thread(path.read_bytes)
    if len(content) > _MAX_ATTACHMENT_BYTES:
        raise ValueError(
            f"File attachment {filename!r} exceeds {_MAX_ATTACHMENT_BYTES} byte limit."
        )
    return AttachmentData(
        filename=filename,
        content=content,
        mimetype=_guess_mimetype(filename, None),
    )


async def _resolve_url_attachment(url: str, index: int) -> AttachmentData:
    content, content_type = await asyncio.to_thread(_fetch_url_attachment, url)
    parsed = urlparse(url)
    filename = Path(parsed.path).name or f"attachment-{index}.bin"
    return AttachmentData(
        filename=filename,
        content=content,
        mimetype=_guess_mimetype(filename, content_type),
    )


_ALLOWED_URL_SCHEMES = {"http", "https"}
_MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024  # 25 MB default


def _fetch_url_attachment(url: str) -> tuple[bytes, str | None]:
    parsed_scheme = urlparse(url).scheme.lower()
    if parsed_scheme not in _ALLOWED_URL_SCHEMES:
        raise ValueError(f"Unsupported URL scheme {parsed_scheme!r}; only http/https are allowed.")
    with urlopen(url, timeout=10) as response:  # noqa: S310 — scheme validated above
        content_type = response.headers.get_content_type()
        data = response.read(_MAX_ATTACHMENT_BYTES + 1)
        if len(data) > _MAX_ATTACHMENT_BYTES:
            raise ValueError(f"URL attachment exceeds {_MAX_ATTACHMENT_BYTES} byte limit.")
        return data, content_type


def _guess_mimetype(filename: str, explicit: Any) -> str:
    if explicit:
        return str(explicit)
    guessed, _encoding = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"
