"""Unit tests for the PostgreSQL backup engine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from openviper.db.tools.backup.postgres import PostgresBackupEngine, _build_pg_env


class TestBuildPgEnv:
    def test_parses_host_user_db(self) -> None:
        flags, env = _build_pg_env("postgresql://user@host/mydb")
        assert "-h" in flags
        assert "host" in flags
        assert "-U" in flags
        assert "user" in flags
        assert "-d" in flags
        assert "mydb" in flags

    def test_password_goes_to_env_not_flags(self) -> None:
        flags, env = _build_pg_env("postgresql://user:secret@host/db")
        assert "PGPASSWORD" in env
        assert env["PGPASSWORD"] == "secret"
        flag_str = " ".join(flags)
        assert "secret" not in flag_str

    def test_port_included_when_present(self) -> None:
        flags, _ = _build_pg_env("postgresql://user@host:5434/db")
        assert "-p" in flags
        assert "5434" in flags

    def test_asyncpg_driver_stripped(self) -> None:
        flags, _ = _build_pg_env("postgresql+asyncpg://user@host/db")
        assert "-h" in flags

    def test_no_password_pgpassword_absent(self) -> None:
        _, env = _build_pg_env("postgresql://user@host/db")
        assert "PGPASSWORD" not in env or env.get("PGPASSWORD", "") == ""


class TestPostgresBackupEngineDump:
    @pytest.mark.asyncio
    async def test_calls_pg_dump_and_returns_path(self, tmp_path: Path) -> None:
        engine = PostgresBackupEngine()

        async def fake_run(args, env=None, timeout=3600):
            # Simulate pg_dump writing the file
            dest = next(args[i + 1] for i, a in enumerate(args) if a == "-f")
            Path(dest).write_text("-- SQL dump", encoding="utf-8")
            return (0, "", "")

        with patch(
            "openviper.db.tools.backup.postgres.run_subprocess",
            side_effect=fake_run,
        ):
            result = await engine.dump("postgresql://u:p@host/db", tmp_path)

        assert result == tmp_path / "backup.sql"

    @pytest.mark.asyncio
    async def test_raises_on_pg_dump_failure(self, tmp_path: Path) -> None:
        engine = PostgresBackupEngine()

        async def fake_run(args, env=None, timeout=3600):
            return (1, "", "FATAL: connection refused")

        with patch("openviper.db.tools.backup.postgres.run_subprocess", side_effect=fake_run):
            with pytest.raises(RuntimeError, match="pg_dump failed"):
                await engine.dump("postgresql://u:p@host/db", tmp_path)

    def test_engine_name_is_postgres(self) -> None:
        assert PostgresBackupEngine.engine_name == "postgres"


class TestPostgresBackupEngineRestore:
    @pytest.mark.asyncio
    async def test_calls_psql_with_file(self, tmp_path: Path) -> None:
        engine = PostgresBackupEngine()
        sql_file = tmp_path / "backup.sql"
        sql_file.write_text("-- SQL", encoding="utf-8")
        captured_args: list[list[str]] = []

        async def fake_run(args, env=None, timeout=3600):
            captured_args.append(args)
            return (0, "", "")

        with patch("openviper.db.tools.backup.postgres.run_subprocess", side_effect=fake_run):
            await engine.restore("postgresql://u:p@host/db", sql_file)

        assert captured_args[0][0] == "psql"
        assert str(sql_file) in captured_args[0]

    @pytest.mark.asyncio
    async def test_raises_on_psql_failure(self, tmp_path: Path) -> None:
        engine = PostgresBackupEngine()
        sql_file = tmp_path / "backup.sql"
        sql_file.write_text("bad sql", encoding="utf-8")

        async def fake_run(args, env=None, timeout=3600):
            return (1, "", "ERROR: syntax error")

        with patch("openviper.db.tools.backup.postgres.run_subprocess", side_effect=fake_run):
            with pytest.raises(RuntimeError, match="psql failed"):
                await engine.restore("postgresql://u:p@host/db", sql_file)
