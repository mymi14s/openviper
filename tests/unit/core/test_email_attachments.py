"""Unit tests targeting coverage gaps in :mod:`openviper.core.email.attachments`.

The goal is to validate the attachment normalization surface (dict/tuple/path/url)
without performing real network access.
"""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openviper.core.email.attachments import (
    AttachmentData,
    attachment_from_payload,
    attachment_to_payload,
    fetch_url_attachment,
    resolve_attachment,
    resolve_attachments,
)


class TestAttachmentPayloadRoundTrip:
    def test_payload_roundtrip(self) -> None:
        original = AttachmentData(filename="report.txt", content=b"hello", mimetype="text/plain")
        payload = attachment_to_payload(original)

        assert payload["filename"] == "report.txt"
        assert payload["content_b64"] == base64.b64encode(b"hello").decode("ascii")
        assert payload["mimetype"] == "text/plain"

        restored = attachment_from_payload(payload)
        assert restored == original


class TestResolveAttachments:
    @pytest.mark.asyncio
    async def test_resolve_attachments_empty_returns_list(self) -> None:
        assert await resolve_attachments(None) == []
        assert await resolve_attachments([]) == []

    @pytest.mark.asyncio
    async def test_resolve_attachment_accepts_common_inputs(self, tmp_path: Path) -> None:
        file_path = tmp_path / "a.txt"
        file_path.write_bytes(b"file")

        response = MagicMock()
        response.headers.get_content_type.return_value = "text/plain"
        response.read.return_value = b"url"
        url_ctx = MagicMock()
        url_ctx.__enter__.return_value = response
        url_ctx.__exit__.return_value = None

        with (
            patch("openviper.core.email.attachments.urlopen", return_value=url_ctx),
            patch("openviper.core.email.attachments.is_private_hostname", return_value=False),
            patch("openviper.core.email.attachments.ATTACHMENT_ALLOWED_DIRS", [str(tmp_path)]),
        ):
            resolved = await resolve_attachments(
                [
                    AttachmentData(filename="x.bin", content=b"x"),
                    {"content": "hello", "filename": "msg.txt"},
                    {
                        "content_b64": base64.b64encode(b"b64").decode("ascii"),
                        "filename": "b64.bin",
                    },
                    {"path": str(file_path)},
                    ("tuple.txt", b"tuple", "text/plain"),
                    b"raw",
                    file_path,
                    str(file_path),
                    "https://example.com/data.bin",
                    ("named.bin", "https://example.com/other.bin"),
                ]
            )

        assert [item.filename for item in resolved] == [
            "x.bin",
            "msg.txt",
            "b64.bin",
            "a.txt",
            "tuple.txt",
            "attachment-6.bin",
            "a.txt",
            "a.txt",
            "data.bin",
            "named.bin",
        ]
        assert resolved[1].content == b"hello"
        assert resolved[8].content == b"url"

    @pytest.mark.asyncio
    async def test_dict_attachment_path_overrides_mimetype(self, tmp_path: Path) -> None:
        file_path = tmp_path / "a.txt"
        file_path.write_bytes(b"x")

        with patch("openviper.core.email.attachments.ATTACHMENT_ALLOWED_DIRS", [str(tmp_path)]):
            attachment = await resolve_attachment(
                {"path": str(file_path), "mimetype": "text/custom"},
                index=1,
            )

        assert attachment.mimetype == "text/custom"

    @pytest.mark.asyncio
    async def test_dict_attachment_url_overrides_filename_and_mimetype(self) -> None:
        response = MagicMock()
        response.headers.get_content_type.return_value = "text/plain"
        response.read.return_value = b"payload"
        url_ctx = MagicMock()
        url_ctx.__enter__.return_value = response
        url_ctx.__exit__.return_value = None

        with (
            patch("openviper.core.email.attachments.urlopen", return_value=url_ctx),
            patch("openviper.core.email.attachments.is_private_hostname", return_value=False),
        ):
            attachment = await resolve_attachment(
                {
                    "url": "https://example.com/file.bin",
                    "filename": "override.bin",
                    "mimetype": "application/custom",
                },
                index=1,
            )

        assert attachment.filename == "override.bin"
        assert attachment.mimetype == "application/custom"
        assert attachment.content == b"payload"

    @pytest.mark.asyncio
    async def test_tuple_attachment_string_payload_existing_file_is_file(
        self, tmp_path: Path
    ) -> None:
        file_path = tmp_path / "note.txt"
        file_path.write_bytes(b"note")

        with patch("openviper.core.email.attachments.ATTACHMENT_ALLOWED_DIRS", [str(tmp_path)]):
            attachment = await resolve_attachment(("named.txt", str(file_path)), index=1)
        assert attachment.filename == "named.txt"
        assert attachment.content == b"note"

    @pytest.mark.asyncio
    async def test_errors_for_invalid_attachment_inputs(self, tmp_path: Path) -> None:
        with pytest.raises(TypeError):
            await resolve_attachment(object(), index=1)

        with pytest.raises(TypeError, match="must include one of"):
            await resolve_attachment({"unexpected": True}, index=1)

        with pytest.raises(TypeError, match="must be bytes or str"):
            await resolve_attachment({"content": 123}, index=1)

        with pytest.raises(TypeError, match="tuple must be"):
            await resolve_attachment(("a", b"b", "c", "d"), index=1)

        with pytest.raises(TypeError, match="Unsupported attachment tuple payload"):
            await resolve_attachment(("a", 1), index=1)

        large_path = tmp_path / "big.bin"
        large_path.write_bytes(b"x" * 10)
        with (
            patch("openviper.core.email.attachments.MAX_ATTACHMENT_BYTES", 5),
            patch("openviper.core.email.attachments.ATTACHMENT_ALLOWED_DIRS", [str(tmp_path)]),
        ):
            with pytest.raises(ValueError, match="exceeds"):
                await resolve_attachment(large_path, index=1)

    @pytest.mark.asyncio
    async def test_allowed_directory_check_rejects_prefix_sibling(self, tmp_path: Path) -> None:
        allowed = tmp_path / "allowed"
        sibling = tmp_path / "allowed_evil"
        allowed.mkdir()
        sibling.mkdir()
        file_path = sibling / "secret.txt"
        file_path.write_bytes(b"secret")

        with patch("openviper.core.email.attachments.ATTACHMENT_ALLOWED_DIRS", [str(allowed)]):
            with pytest.raises(ValueError, match="outside allowed directories"):
                await resolve_attachment(file_path, index=1)


class TestFetchUrlAttachment:
    def test_rejects_non_http_schemes(self) -> None:
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            fetch_url_attachment("file:///etc/passwd")

    def test_rejects_oversized_payloads(self) -> None:
        response = MagicMock()
        response.headers.get_content_type.return_value = "application/octet-stream"
        response.read.return_value = b"x" * 6
        url_ctx = MagicMock()
        url_ctx.__enter__.return_value = response
        url_ctx.__exit__.return_value = None

        with (
            patch("openviper.core.email.attachments.MAX_ATTACHMENT_BYTES", 5),
            patch("openviper.core.email.attachments.is_private_hostname", return_value=False),
            patch("openviper.core.email.attachments.urlopen", return_value=url_ctx),
        ):
            with pytest.raises(ValueError, match="exceeds"):
                fetch_url_attachment("https://example.com/file.bin")

    def test_rejects_private_ip_ssrf(self) -> None:
        with pytest.raises(ValueError, match="private/reserved"):
            fetch_url_attachment("http://127.0.0.1/admin/")

    def test_rejects_cloud_metadata_ssrf(self) -> None:
        with pytest.raises(ValueError, match="private/reserved"):
            fetch_url_attachment("http://169.254.169.254/latest/meta-data/")

    def test_rejects_no_hostname(self) -> None:
        with pytest.raises(ValueError, match="no hostname"):
            fetch_url_attachment("https:///path")

    def test_rejects_redirects_before_reading_payload(self) -> None:
        with (
            patch("openviper.core.email.attachments.is_private_hostname", return_value=False),
            patch(
                "openviper.core.email.attachments.build_opener",
                side_effect=ValueError("URL attachment redirects are not allowed"),
            ),
            pytest.raises(ValueError, match="redirects are not allowed"),
        ):
            fetch_url_attachment("https://example.com/file.bin")

    def test_rejects_private_peer_after_connection(self) -> None:
        response = MagicMock()
        response.getpeername.return_value = ("127.0.0.1", 443)
        response.headers.get_content_type.return_value = "text/plain"
        response.read.return_value = b"payload"
        url_ctx = MagicMock()
        url_ctx.__enter__.return_value = response
        url_ctx.__exit__.return_value = None
        opener = MagicMock()
        opener.open.return_value = url_ctx

        with (
            patch("openviper.core.email.attachments.is_private_hostname", return_value=False),
            patch("openviper.core.email.attachments.build_opener", return_value=opener),
            pytest.raises(ValueError, match="private/reserved address"),
        ):
            fetch_url_attachment("https://example.com/file.bin")
