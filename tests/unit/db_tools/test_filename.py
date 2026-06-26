"""Unit tests for openviper.db.tools.utils.filename."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from openviper.db.tools.utils.filename import (
    generate_backup_filename,
    parse_db_name_from_url,
    sanitize_db_name,
)


class TestSanitizeDbName:
    def test_alphanumeric_unchanged(self) -> None:
        assert sanitize_db_name("mydb123") == "mydb123"

    def test_underscores_unchanged(self) -> None:
        assert sanitize_db_name("my_db_name") == "my_db_name"

    def test_spaces_replaced_with_underscores(self) -> None:
        assert sanitize_db_name("my db") == "my_db"

    def test_hyphens_replaced(self) -> None:
        assert sanitize_db_name("my-db") == "my_db"

    def test_dots_replaced(self) -> None:
        assert sanitize_db_name("my.db") == "my_db"

    def test_consecutive_unsafe_chars_collapsed(self) -> None:
        assert sanitize_db_name("my--db!!") == "my_db"

    def test_empty_string_returns_database(self) -> None:
        assert sanitize_db_name("") == "database"

    def test_all_unsafe_returns_database(self) -> None:
        assert sanitize_db_name("!!!") == "database"

    def test_leading_trailing_underscores_stripped(self) -> None:
        assert sanitize_db_name("_mydb_") == "mydb"

    def test_slashes_replaced(self) -> None:
        result = sanitize_db_name("some/db/path")
        assert "/" not in result


class TestGenerateBackupFilename:
    def test_compressed_extension(self) -> None:
        name = generate_backup_filename("mydb")
        assert name.endswith(".tar.gz")

    def test_uncompressed_extension(self) -> None:
        name = generate_backup_filename("mydb", compress=False)
        assert name.endswith(".sql")

    def test_contains_db_name(self) -> None:
        name = generate_backup_filename("postgres")
        assert name.startswith("postgres_")

    def test_datetime_stamp_format(self) -> None:
        name = generate_backup_filename("mydb")
        # Should match: mydb_YYYYMMDD-HHMMSS.tar.gz
        pattern = r"^mydb_\d{8}-\d{6}\.tar\.gz$"
        assert re.match(pattern, name), f"Filename {name!r} did not match pattern"

    def test_generates_utc_based_stamp(self) -> None:
        before = datetime.now(tz=UTC).strftime("%Y%m%d")
        name = generate_backup_filename("db")
        after = datetime.now(tz=UTC).strftime("%Y%m%d")
        stamp = name.split("_", 1)[1].split(".")[0][:8]
        assert before <= stamp <= after

    def test_sanitizes_db_name(self) -> None:
        name = generate_backup_filename("my-db")
        assert name.startswith("my_db_")


class TestParseDbNameFromUrl:
    def test_sqlite_file_url(self) -> None:
        assert parse_db_name_from_url("sqlite:///db.sqlite3") == "db"

    def test_sqlite_relative_path(self) -> None:
        assert parse_db_name_from_url("sqlite:///./myapp.db") == "myapp"

    def test_postgres_url(self) -> None:
        assert parse_db_name_from_url("postgresql://user:pass@host/mydb") == "mydb"

    def test_postgres_asyncpg_url(self) -> None:
        assert parse_db_name_from_url("postgresql+asyncpg://user:pass@host/testdb") == "testdb"

    def test_mysql_url(self) -> None:
        assert parse_db_name_from_url("mysql://user:pass@host/shopdb") == "shopdb"

    def test_url_without_db_name_uses_fallback(self) -> None:
        result = parse_db_name_from_url("sqlite:///")
        assert result == "database"

    def test_query_string_ignored(self) -> None:
        result = parse_db_name_from_url("postgresql://host/mydb?sslmode=require")
        assert result == "mydb"

    def test_sqlite_without_extension(self) -> None:
        result = parse_db_name_from_url("sqlite:///mydb")
        assert result == "mydb"
