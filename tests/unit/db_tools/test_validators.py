"""Unit tests for openviper.db.tools.utils.validators."""

from __future__ import annotations

from pathlib import Path

import pytest

from openviper.db.tools.utils.validators import (
    ValidationError,
    validate_archive_member,
    validate_backup_file,
    validate_backup_path,
    validate_subprocess_arg,
)


class TestValidateBackupPath:
    def test_valid_relative_path(self, tmp_path: Path) -> None:
        result = validate_backup_path(tmp_path)
        assert result == tmp_path.resolve()

    def test_path_traversal_rejected(self) -> None:
        with pytest.raises(ValidationError, match="traversal"):
            validate_backup_path("../../../etc")

    def test_filesystem_root_rejected(self) -> None:
        with pytest.raises(ValidationError, match="root"):
            validate_backup_path("/")

    def test_returns_resolved_path(self, tmp_path: Path) -> None:
        result = validate_backup_path(str(tmp_path))
        assert isinstance(result, Path)
        assert result.is_absolute()


class TestValidateBackupFile:
    def test_existing_file_accepted(self, tmp_path: Path) -> None:
        f = tmp_path / "backup.tar.gz"
        f.write_bytes(b"data")
        result = validate_backup_file(f)
        assert result == f.resolve()

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="not found"):
            validate_backup_file(tmp_path / "nonexistent.tar.gz")

    def test_directory_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="not a regular file"):
            validate_backup_file(tmp_path)

    def test_path_traversal_in_file_path_rejected(self) -> None:
        with pytest.raises(ValidationError, match="traversal"):
            validate_backup_file("../../../etc/passwd")


class TestValidateSubprocessArg:
    def test_safe_argument_returned_unchanged(self) -> None:
        assert validate_subprocess_arg("/usr/bin/pg_dump") == "/usr/bin/pg_dump"

    def test_semicolon_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Unsafe"):
            validate_subprocess_arg("mydb; rm -rf /")

    def test_pipe_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Unsafe"):
            validate_subprocess_arg("mydb | cat /etc/passwd")

    def test_backtick_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Unsafe"):
            validate_subprocess_arg("`whoami`")

    def test_dollar_sign_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Unsafe"):
            validate_subprocess_arg("$HOME")

    def test_newline_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Unsafe"):
            validate_subprocess_arg("arg\nrm -rf /")

    def test_null_byte_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Unsafe"):
            validate_subprocess_arg("arg\x00evil")

    def test_normal_db_name_accepted(self) -> None:
        assert validate_subprocess_arg("postgres_db_1") == "postgres_db_1"

    def test_host_port_flag_accepted(self) -> None:
        assert validate_subprocess_arg("-h") == "-h"


class TestValidateArchiveMember:
    def test_safe_member_accepted(self, tmp_path: Path) -> None:
        result = validate_archive_member("backup.sql", tmp_path)
        assert result == (tmp_path / "backup.sql").resolve()

    def test_traversal_member_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="escapes"):
            validate_archive_member("../../etc/passwd", tmp_path)

    def test_absolute_member_trapped_if_escaping(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="escapes"):
            validate_archive_member("/etc/passwd", tmp_path)

    def test_nested_safe_member_accepted(self, tmp_path: Path) -> None:
        result = validate_archive_member("subdir/backup.sql", tmp_path)
        assert str(result).startswith(str(tmp_path.resolve()))
