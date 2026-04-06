"""Unit tests for the MSSQL backup engine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from openviper.db.tools.backup.mssql import MSSQLBackupEngine, _parse_mssql_url


class TestParseMssqlUrl:
    def test_parses_user_password_host_db(self) -> None:
        conn = _parse_mssql_url("mssql://sa:pwd@sqlhost/mydb")
        assert conn["user"] == "sa"
        assert conn["password"] == "pwd"
        assert conn["host"] == "sqlhost"
        assert conn["database"] == "mydb"

    def test_default_port_1433(self) -> None:
        conn = _parse_mssql_url("mssql://sa@sqlhost/mydb")
        assert conn["port"] == "1433"

    def test_pyodbc_driver_stripped(self) -> None:
        conn = _parse_mssql_url("mssql+pyodbc://sa@host/db")
        assert conn["host"] == "host"

    def test_aioodbc_driver_stripped(self) -> None:
        conn = _parse_mssql_url("mssql+aioodbc://sa@host/db")
        assert conn["host"] == "host"


class TestMSSQLBackupEngineDump:
    @pytest.mark.asyncio
    async def test_calls_sqlcmd_and_writes_backup_sql(self, tmp_path: Path) -> None:
        engine = MSSQLBackupEngine()
        captured: list[list[str]] = []

        async def fake_run(args, env=None, timeout=3600):
            captured.append(args)
            return (0, "", "")

        with patch("openviper.db.tools.backup.mssql.run_subprocess", side_effect=fake_run):
            result = await engine.dump("mssql://sa:pwd@sqlhost/mydb", tmp_path)

        assert captured[0][0] == "sqlcmd"
        assert result == tmp_path / "backup.sql"
        assert (tmp_path / "backup.sql").exists()

    @pytest.mark.asyncio
    async def test_raises_on_sqlcmd_failure(self, tmp_path: Path) -> None:
        engine = MSSQLBackupEngine()

        async def fake_run(args, env=None, timeout=3600):
            return (1, "", "Login failed")

        with patch("openviper.db.tools.backup.mssql.run_subprocess", side_effect=fake_run):
            with pytest.raises(RuntimeError, match="sqlcmd backup failed"):
                await engine.dump("mssql://sa:pwd@sqlhost/mydb", tmp_path)

    def test_engine_name_is_mssql(self) -> None:
        assert MSSQLBackupEngine.engine_name == "mssql"


class TestMSSQLBackupEngineRestore:
    @pytest.mark.asyncio
    async def test_calls_sqlcmd_restore(self, tmp_path: Path) -> None:
        engine = MSSQLBackupEngine()
        sql_file = tmp_path / "backup.sql"
        sql_file.write_text("T-SQL", encoding="utf-8")
        captured: list[list[str]] = []

        async def fake_run(args, env=None, timeout=3600):
            captured.append(args)
            return (0, "", "")

        with patch("openviper.db.tools.backup.mssql.run_subprocess", side_effect=fake_run):
            await engine.restore("mssql://sa:pwd@sqlhost/mydb", sql_file)

        assert captured[0][0] == "sqlcmd"

    @pytest.mark.asyncio
    async def test_force_includes_replace_keyword(self, tmp_path: Path) -> None:
        engine = MSSQLBackupEngine()
        sql_file = tmp_path / "backup.sql"
        sql_file.write_text("T-SQL", encoding="utf-8")
        captured: list[list[str]] = []

        async def fake_run(args, env=None, timeout=3600):
            captured.append(args)
            return (0, "", "")

        with patch("openviper.db.tools.backup.mssql.run_subprocess", side_effect=fake_run):
            await engine.restore("mssql://sa:pwd@sqlhost/mydb", sql_file, force=True)

        # The restore SQL should include WITH REPLACE
        query_arg = next(
            (args[i + 1] for args in captured for i, a in enumerate(args) if a == "-Q"),
            "",
        )
        assert "REPLACE" in query_arg

    @pytest.mark.asyncio
    async def test_raises_on_sqlcmd_restore_failure(self, tmp_path: Path) -> None:
        engine = MSSQLBackupEngine()
        sql_file = tmp_path / "backup.sql"
        sql_file.write_text("T-SQL", encoding="utf-8")

        async def fake_run(args, env=None, timeout=3600):
            return (1, "", "Cannot open database")

        with patch("openviper.db.tools.backup.mssql.run_subprocess", side_effect=fake_run):
            with pytest.raises(RuntimeError, match="sqlcmd restore failed"):
                await engine.restore("mssql://sa:pwd@sqlhost/mydb", sql_file)
