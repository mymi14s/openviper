"""Unit tests for openviper.db.tools.compression.tar."""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from openviper.db.tools.compression.tar import (
    create_tar_gz,
    extract_tar_gz,
    list_tar_gz_members,
)
from openviper.db.tools.utils.validators import ValidationError


class TestCreateTarGz:
    @pytest.mark.asyncio
    async def test_creates_archive_with_all_files(self, tmp_path: Path) -> None:
        sql = tmp_path / "backup.sql"
        meta = tmp_path / "metadata.json"
        sql.write_text("SELECT 1;", encoding="utf-8")
        meta.write_text('{"engine":"sqlite"}', encoding="utf-8")

        archive = tmp_path / "archive.tar.gz"
        await create_tar_gz(archive, [sql, meta])

        assert archive.exists()
        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
        assert "backup.sql" in names
        assert "metadata.json" in names

    @pytest.mark.asyncio
    async def test_missing_source_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            await create_tar_gz(
                tmp_path / "out.tar.gz",
                [tmp_path / "nonexistent.sql"],
            )

    @pytest.mark.asyncio
    async def test_archive_uses_bare_filenames(self, tmp_path: Path) -> None:
        subdir = tmp_path / "deep" / "path"
        subdir.mkdir(parents=True)
        f = subdir / "backup.sql"
        f.write_text("SQL", encoding="utf-8")

        archive = tmp_path / "out.tar.gz"
        await create_tar_gz(archive, [f])

        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
        # No directory prefix — only bare filename.
        assert names == ["backup.sql"]


class TestExtractTarGz:
    @pytest.mark.asyncio
    async def test_extracts_all_members(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        extract_dir = tmp_path / "out"
        archive = tmp_path / "test.tar.gz"

        (src_dir / "backup.sql").write_text("SQL", encoding="utf-8")
        (src_dir / "metadata.json").write_text("{}", encoding="utf-8")

        await create_tar_gz(archive, [src_dir / "backup.sql", src_dir / "metadata.json"])
        extracted = await extract_tar_gz(archive, extract_dir)

        assert len(extracted) == 2
        names = {p.name for p in extracted}
        assert "backup.sql" in names
        assert "metadata.json" in names

    @pytest.mark.asyncio
    async def test_path_traversal_in_archive_rejected(self, tmp_path: Path) -> None:
        archive = tmp_path / "malicious.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo(name="../../evil.sh")
            info.size = 0
            import io

            tar.addfile(info, io.BytesIO(b""))

        with pytest.raises(ValidationError, match="escapes"):
            await extract_tar_gz(archive, tmp_path / "extract")

    @pytest.mark.asyncio
    async def test_creates_destination_directory(self, tmp_path: Path) -> None:
        src = tmp_path / "f.sql"
        src.write_text("x", encoding="utf-8")
        archive = tmp_path / "a.tar.gz"
        await create_tar_gz(archive, [src])

        dest = tmp_path / "new_subdir"
        assert not dest.exists()
        await extract_tar_gz(archive, dest)
        assert dest.exists()


class TestListTarGzMembers:
    def test_returns_member_names(self, tmp_path: Path) -> None:
        f = tmp_path / "backup.sql"
        f.write_bytes(b"SQL")
        archive = tmp_path / "a.tar.gz"

        with tarfile.open(archive, "w:gz") as tar:
            tar.add(f, arcname="backup.sql")

        members = list_tar_gz_members(archive)
        assert "backup.sql" in members

    def test_returns_list(self, tmp_path: Path) -> None:
        archive = tmp_path / "empty.tar.gz"
        with tarfile.open(archive, "w:gz"):
            pass
        assert list_tar_gz_members(archive) == []
