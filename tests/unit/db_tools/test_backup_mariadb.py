"""Unit tests for the MariaDB backup engine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from openviper.db.tools.backup.mariadb import MariaDBBackupEngine, _build_mysql_args


class TestBuildMysqlArgs:
    def test_parses_host_user_db(self) -> None:
        flags, db_name, password = _build_mysql_args("mysql://user@host/shopdb")
        assert "--host=host" in flags
        assert "--user=user" in flags
        assert db_name == "shopdb"

    def test_password_returned_separately(self) -> None:
        flags, _, password = _build_mysql_args("mysql://user:secret@host/db")
        assert password == "secret"
        assert not any(f.startswith("--password") for f in flags)

    def test_port_included_when_present(self) -> None:
        flags, _, _pw = _build_mysql_args("mysql://user@host:3307/db")
        assert "--port=3307" in flags

    def test_aiomysql_driver_stripped(self) -> None:
        flags, db_name, _pw = _build_mysql_args("mysql+aiomysql://user@host/db")
        assert "--host=host" in flags

    def test_pymysql_driver_stripped(self) -> None:
        flags, db_name, _pw = _build_mysql_args("mysql+pymysql://user@host/db")
        assert "--host=host" in flags


class TestMariaDBBackupEngineDump:
    @pytest.mark.asyncio
    async def test_writes_stdout_to_backup_sql(self, tmp_path: Path) -> None:
        engine = MariaDBBackupEngine()

        async def fake_run(args, env=None, timeout=3600):
            return (0, "-- MySQL dump", "")

        with patch("openviper.db.tools.backup.mariadb.run_subprocess", side_effect=fake_run):
            result = await engine.dump("mysql://u:p@host/db", tmp_path)

        assert result == tmp_path / "backup.sql"
        assert (tmp_path / "backup.sql").read_text(encoding="utf-8") == "-- MySQL dump"

    @pytest.mark.asyncio
    async def test_raises_on_mysqldump_failure(self, tmp_path: Path) -> None:
        engine = MariaDBBackupEngine()

        async def fake_run(args, env=None, timeout=3600):
            return (1, "", "Access denied")

        with patch("openviper.db.tools.backup.mariadb.run_subprocess", side_effect=fake_run):
            with pytest.raises(RuntimeError, match="mysqldump failed"):
                await engine.dump("mysql://u:p@host/db", tmp_path)

    def test_engine_name_is_mariadb(self) -> None:
        assert MariaDBBackupEngine.engine_name == "mariadb"


class TestMariaDBBackupEngineRestore:
    @pytest.mark.asyncio
    async def test_calls_mysql_with_file(self, tmp_path: Path) -> None:
        engine = MariaDBBackupEngine()
        sql_file = tmp_path / "backup.sql"
        sql_file.write_text("-- SQL", encoding="utf-8")
        captured: list[list[str]] = []

        async def fake_run(args, env=None, timeout=3600):
            captured.append(args)
            return (0, "", "")

        with patch("openviper.db.tools.backup.mariadb.run_subprocess", side_effect=fake_run):
            await engine.restore("mysql://u:p@host/db", sql_file)

        assert captured[0][0] == "mysql"

    @pytest.mark.asyncio
    async def test_raises_on_mysql_restore_failure(self, tmp_path: Path) -> None:
        engine = MariaDBBackupEngine()
        sql_file = tmp_path / "backup.sql"
        sql_file.write_text("bad", encoding="utf-8")

        async def fake_run(args, env=None, timeout=3600):
            return (1, "", "ERROR 1046")

        with patch("openviper.db.tools.backup.mariadb.run_subprocess", side_effect=fake_run):
            with pytest.raises(RuntimeError, match="mysql failed"):
                await engine.restore("mysql://u:p@host/db", sql_file)
