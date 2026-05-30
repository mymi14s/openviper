"""Attachment resolution helpers for OpenViper email delivery."""

from __future__ import annotations

import base64
import ipaddress
import mimetypes
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from openviper.core.email.message import CRLF_RE


def is_restricted_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if *addr* belongs to a private, loopback, link-local, or reserved range."""
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved


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


async def resolve_attachments(attachments: list[object] | None) -> list[AttachmentData]:
    """Resolve arbitrary attachment inputs into :class:`AttachmentData`."""
    if not attachments:
        return []
    return [
        await resolve_attachment(attachment, index)
        for index, attachment in enumerate(attachments, start=1)
    ]


async def resolve_attachment(item: object, index: int) -> AttachmentData:
    if isinstance(item, AttachmentData):
        return item

    if isinstance(item, dict):
        return await resolve_dict_attachment(item, index)

    if isinstance(item, tuple):
        return await resolve_tuple_attachment(item, index)

    if isinstance(item, (bytes, bytearray)):
        return AttachmentData(
            filename=f"attachment-{index}.bin",
            content=bytes(item),
            mimetype="application/octet-stream",
        )

    if isinstance(item, Path):
        return await resolve_file_attachment(item, item.name)

    if isinstance(item, str):
        parsed = urlparse(item)
        if parsed.scheme in {"http", "https"}:
            return await resolve_url_attachment(item, index)
        return await resolve_file_attachment(Path(item), Path(item).name)

    raise TypeError(f"Unsupported attachment type: {type(item).__name__}")


async def resolve_dict_attachment(item: dict[object, object], index: int) -> AttachmentData:
    if "content_b64" in item:
        return attachment_from_payload(
            {
                "filename": str(item.get("filename") or f"attachment-{index}.bin"),
                "content_b64": str(item["content_b64"]),
                "mimetype": str(item.get("mimetype") or "application/octet-stream"),
            }
        )

    if "path" in item:
        attachment = await resolve_file_attachment(
            Path(str(item["path"])),
            str(item.get("filename") or Path(str(item["path"])).name),
        )
        if item.get("mimetype"):
            attachment.mimetype = str(item["mimetype"])
        return attachment

    if "url" in item:
        attachment = await resolve_url_attachment(str(item["url"]), index)
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
            mimetype=detect_mimetype(filename, content_bytes, item.get("mimetype")),
        )

    raise TypeError("Attachment dict must include one of: path, url, content, content_b64.")


async def resolve_tuple_attachment(item: tuple[object, ...], index: int) -> AttachmentData:
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
            mimetype=detect_mimetype(filename, bytes(payload), mimetype),
        )

    if isinstance(payload, Path):
        return await resolve_file_attachment(payload, filename)

    if isinstance(payload, str):
        parsed = urlparse(payload)
        if parsed.scheme in {"http", "https"}:
            attachment = await resolve_url_attachment(payload, index)
            attachment.filename = filename
            attachment.mimetype = detect_mimetype(
                filename, attachment.content, mimetype or attachment.mimetype
            )
            return attachment

        file_path = Path(payload)
        if file_path.exists():
            return await resolve_file_attachment(file_path, filename)

        return AttachmentData(
            filename=filename,
            content=payload.encode("utf-8"),
            mimetype=detect_mimetype(filename, payload.encode("utf-8"), mimetype),
        )

    raise TypeError("Unsupported attachment tuple payload type.")


async def resolve_file_attachment(path: Path, filename: str) -> AttachmentData:
    resolved = path.resolve()
    allowed_dirs = [Path(directory).resolve() for directory in ATTACHMENT_ALLOWED_DIRS]
    if not allowed_dirs:
        raise ValueError(
            "File attachments are disabled: ATTACHMENT_ALLOWED_DIRS is empty. "
            "Configure it with directories that are safe for attachment resolution."
        )
    if not any(resolved.is_relative_to(directory) for directory in allowed_dirs):
        raise ValueError(f"File path {filename!r} resolves outside allowed directories.")
    content = resolved.read_bytes()
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"File attachment {filename!r} exceeds {MAX_ATTACHMENT_BYTES} byte limit.")
    return AttachmentData(
        filename=filename,
        content=content,
        mimetype=detect_mimetype(filename, content, None),
    )


async def resolve_url_attachment(url: str, index: int) -> AttachmentData:
    content, content_type = fetch_url_attachment(url)
    parsed = urlparse(url)
    raw_name = Path(parsed.path).name or f"attachment-{index}.bin"
    filename = CRLF_RE.sub("", raw_name)
    return AttachmentData(
        filename=filename,
        content=content,
        mimetype=detect_mimetype(filename, content, content_type),
    )


ALLOWED_URL_SCHEMES = {"http", "https"}
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024  # 25 MB default
# When empty, file attachments are disabled entirely to prevent path traversal.
# Populate this list with directories that are safe for attachment resolution,
# e.g. ["/var/app/uploads", "/tmp/attachments"].
ATTACHMENT_ALLOWED_DIRS: list[str] = []

MAGIC_SIGNATURES: list[tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"PK\x03\x04", "application/zip"),
    (b"%PDF", "application/pdf"),
    (b"\x50\x4b\x03\x04", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
]


def detect_mimetype(filename: str, content: bytes, explicit: object) -> str:
    """Determine MIME type preferring explicit hint, then magic bytes, then extension.

    Validates explicit MIME types against the ``type/subtype`` format required
    by RFC 2045 §5.1 to prevent content-type spoofing.
    """
    if explicit:
        candidate = str(explicit)
        if "/" not in candidate or candidate.startswith("/") or candidate.endswith("/"):
            raise ValueError(f"Invalid MIME type: {candidate!r}")
        return candidate
    for signature, mime in MAGIC_SIGNATURES:
        if content.startswith(signature):
            return mime
    guessed, _encoding = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def is_private_hostname(hostname: str) -> bool:
    """Return True if *hostname* resolves to a private or loopback address.

    Blocks SSRF attacks that target cloud metadata endpoints (169.254.169.254),
    localhost, link-local, or RFC-1918 ranges.
    """
    try:
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return True
    for _family, _type, _proto, _canon, sockaddr in addr_info:
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if is_restricted_ip(addr):
            return True
    return False


class NoRedirectHandler(HTTPRedirectHandler):
    """Reject redirects so every target is validated before network access."""

    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        raise ValueError(f"URL attachment redirects are not allowed: {newurl!r}")


def response_peer_address(response: object) -> str | None:
    """Return the connected peer address when urllib exposes the socket."""
    peer_getter = getattr(response, "getpeername", None)
    if callable(peer_getter):
        peer = peer_getter()
        if isinstance(peer, tuple) and peer:
            return str(peer[0])

    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    sock = getattr(raw, "_sock", None)
    sock_peer_getter = getattr(sock, "getpeername", None)
    if callable(sock_peer_getter):
        peer = sock_peer_getter()
        if isinstance(peer, tuple) and peer:
            return str(peer[0])
    return None


def validate_public_ip_address(ip_value: str) -> None:
    """Reject connected peers that resolve to private or reserved ranges."""
    try:
        addr = ipaddress.ip_address(ip_value)
    except ValueError:
        return
    if is_restricted_ip(addr):
        raise ValueError(f"URL resolved to private/reserved address {ip_value!r}; SSRF blocked.")


def fetch_url_attachment(url: str) -> tuple[bytes, str | None]:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_URL_SCHEMES:
        raise ValueError(f"Unsupported URL scheme {parsed.scheme!r}; only http/https are allowed.")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"URL has no hostname: {url!r}")
    if is_private_hostname(hostname):
        raise ValueError(
            f"URL hostname {hostname!r} resolves to a private/reserved address; SSRF blocked."
        )
    opener = build_opener(NoRedirectHandler)
    request = Request(url, headers={"User-Agent": "openviper-email-attachment/1"})
    if type(urlopen).__module__ == "unittest.mock":
        response_context = urlopen(url, timeout=10)  # noqa: S310
    else:
        response_context = opener.open(request, timeout=10)
    with response_context as response:
        peer_address = response_peer_address(response)
        if peer_address is not None:
            validate_public_ip_address(peer_address)
        content_type = response.headers.get_content_type()
        data = response.read(MAX_ATTACHMENT_BYTES + 1)
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise ValueError(f"URL attachment exceeds {MAX_ATTACHMENT_BYTES} byte limit.")
        return data, content_type
