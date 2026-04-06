"""Unit tests for the Oracle backup engine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from openviper.db.tools.backup.oracle import OracleBackupEngine, _parse_oracle_url


class TestParseOracleUrl:
    def test_parses_user_password_host_service(self) -> None:
        conn = _parse_oracle_url("oracle://admin:pwd@orahost:1521/ORCL")
        assert conn["user"] == "admin"
        assert conn["password"] == "pwd"
        assert conn["host"] == "orahost"
        assert conn["port"] == "1521"
        assert conn["service"] == "ORCL"

    def test_default_port_1521(self) -> None:
        conn = _parse_oracle_url("oracle://admin@orahost/ORCL")
        assert conn["port"] == "1521"

    def test_oracledb_driver_stripped(self) -> None:
        conn = _parse_oracle_url("oracle+oracledb://admin@host/SVC")
        assert conn["host"] == "host"


class TestOracleBackupEngineDump:
    @pytest.mark.asyncio
    async def test_calls_expdp_and_returns_path(self, tmp_path: Path) -> None:
        engine = OracleBackupEngine()
        captured: list[list[str]] = []

        async def fake_run(args, env=None, timeout=3600):
            captured.append(args)
            return (0, "", "")

        with patch("openviper.db.tools.backup.oracle.run_subprocess", side_effect=fake_run):
            result = await engine.dump("oracle://user:pwd@host/ORCL", tmp_path)

        assert captured[0][0] == "expdp"
        assert result == tmp_path / "backup.sql"

    @pytest.mark.asyncio
    async def test_raises_on_expdp_failure(self, tmp_path: Path) -> None:
        engine = OracleBackupEngine()

        async def fake_run(args, env=None, timeout=3600):
            return (1, "", "ORA-00001 error")

        with patch("openviper.db.tools.backup.oracle.run_subprocess", side_effect=fake_run):
            with pytest.raises(RuntimeError, match="expdp failed"):
                await engine.dump("oracle://user:pwd@host/ORCL", tmp_path)

    def test_engine_name_is_oracle(self) -> None:
        assert OracleBackupEngine.engine_name == "oracle"


class TestOracleBackupEngineRestore:
    @pytest.mark.asyncio
    async def test_calls_impdp_with_file(self, tmp_path: Path) -> None:
        engine = OracleBackupEngine()
        sql_file = tmp_path / "backup.sql"
        sql_file.write_bytes(b"")
        captured: list[list[str]] = []

        async def fake_run(args, env=None, timeout=3600):
            captured.append(args)
            return (0, "", "")

        with patch("openviper.db.tools.backup.oracle.run_subprocess", side_effect=fake_run):
            await engine.restore("oracle://user:pwd@host/ORCL", sql_file)

        assert captured[0][0] == "impdp"

    @pytest.mark.asyncio
    async def test_force_includes_replace_action(self, tmp_path: Path) -> None:
        engine = OracleBackupEngine()
        sql_file = tmp_path / "backup.sql"
        sql_file.write_bytes(b"")
        captured: list[list[str]] = []

        async def fake_run(args, env=None, timeout=3600):
            captured.append(args)
            return (0, "", "")

        with patch("openviper.db.tools.backup.oracle.run_subprocess", side_effect=fake_run):
            await engine.restore("oracle://user:pwd@host/ORCL", sql_file, force=True)

        assert any("REPLACE" in arg for arg in captured[0])

    @pytest.mark.asyncio
    async def test_no_force_includes_skip_action(self, tmp_path: Path) -> None:
        engine = OracleBackupEngine()
        sql_file = tmp_path / "backup.sql"
        sql_file.write_bytes(b"")
        captured: list[list[str]] = []

        async def fake_run(args, env=None, timeout=3600):
            captured.append(args)
            return (0, "", "")

        with patch("openviper.db.tools.backup.oracle.run_subprocess", side_effect=fake_run):
            await engine.restore("oracle://user:pwd@host/ORCL", sql_file, force=False)

        assert any("SKIP" in arg for arg in captured[0])
