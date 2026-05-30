"""Unit tests for openviper.db.tools.utils.metadata."""

from __future__ import annotations

from pathlib import Path

import pytest

from openviper.db.tools.utils.metadata import (
    build_metadata,
    compute_checksum,
    read_metadata,
    write_metadata,
)


class TestComputeChecksum:
    def test_known_content_returns_correct_sha256(self, tmp_path: Path) -> None:
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello")
        # SHA-256 of b"hello"
        expected = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        assert compute_checksum(f) == expected

    def test_empty_file_has_deterministic_hash(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")
        result = compute_checksum(f)
        assert len(result) == 64
        assert result == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_different_files_produce_different_checksums(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"content_a")
        f2.write_bytes(b"content_b")
        assert compute_checksum(f1) != compute_checksum(f2)


class TestBuildMetadata:
    def test_all_required_fields_present(self) -> None:
        meta = build_metadata(
            database_name="mydb",
            db_engine="sqlite",
            filename="mydb_20260404-120000.tar.gz",
            checksum="abc123",
        )
        assert meta["database_name"] == "mydb"
        assert meta["db_engine"] == "sqlite"
        assert meta["filename"] == "mydb_20260404-120000.tar.gz"
        assert meta["checksum"] == "abc123"
        assert "timestamp" in meta
        assert "openviper_version" in meta

    def test_timestamp_is_iso_format(self) -> None:
        meta = build_metadata(
            database_name="db",
            db_engine="postgres",
            filename="x.tar.gz",
            checksum="aaa",
        )
        # ISO format contains 'T' separator
        assert "T" in meta["timestamp"]

    def test_openviper_version_is_string(self) -> None:
        meta = build_metadata(
            database_name="db",
            db_engine="sqlite",
            filename="x.tar.gz",
            checksum="bbb",
        )
        assert isinstance(meta["openviper_version"], str)


class TestWriteAndReadMetadata:
    def test_write_creates_file(self, tmp_path: Path) -> None:
        meta = {"database_name": "db", "db_engine": "sqlite", "checksum": "abc"}
        dest = tmp_path / "metadata.json"
        write_metadata(meta, dest)
        assert dest.exists()

    def test_write_then_read_roundtrip(self, tmp_path: Path) -> None:
        meta = {"database_name": "testdb", "db_engine": "postgres", "checksum": "xyz"}
        dest = tmp_path / "metadata.json"
        write_metadata(meta, dest)
        result = read_metadata(tmp_path)
        assert result == meta

    def test_read_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="metadata.json"):
            read_metadata(tmp_path)

    def test_read_invalid_json_raises_value_error(self, tmp_path: Path) -> None:
        (tmp_path / "metadata.json").write_text("not json {{{", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid metadata.json"):
            read_metadata(tmp_path)
