"""Unit tests for openviper.db.tools.utils.async_process."""

from __future__ import annotations

import asyncio

import pytest

from openviper.db.tools.utils.async_process import (
    check_returncode,
    run_subprocess,
)
from openviper.db.tools.utils.validators import ValidationError


class TestCheckReturncode:
    def test_zero_returncode_does_not_raise(self) -> None:
        check_returncode(0, "", command="pg_dump")

    def test_nonzero_returncode_raises_runtime_error(self) -> None:
        with pytest.raises(RuntimeError, match="pg_dump failed"):
            check_returncode(1, "some error", command="pg_dump")

    def test_error_message_includes_stderr(self) -> None:
        with pytest.raises(RuntimeError, match="connection refused"):
            check_returncode(2, "connection refused", command="psql")


class TestRunSubprocess:
    @pytest.mark.asyncio
    async def test_safe_arguments_execute_successfully(self) -> None:
        returncode, stdout, stderr = await run_subprocess(["echo", "hello"])
        assert returncode == 0
        assert "hello" in stdout

    @pytest.mark.asyncio
    async def test_unsafe_argument_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="Unsafe"):
            await run_subprocess(["echo", "hello; rm -rf /"])

    @pytest.mark.asyncio
    async def test_missing_executable_raises_os_error(self) -> None:
        with pytest.raises(OSError, match="No such file"):
            await run_subprocess(["nonexistent_command_xyz_abc_123"])

    @pytest.mark.asyncio
    async def test_timeout_kills_process(self) -> None:
        with pytest.raises(asyncio.TimeoutError):
            await run_subprocess(["sleep", "10"], timeout=1)

    @pytest.mark.asyncio
    async def test_returns_stdout_and_stderr(self) -> None:
        returncode, stdout, stderr = await run_subprocess(["echo", "output"])
        assert returncode == 0
        assert stdout.strip() == "output"

    @pytest.mark.asyncio
    async def test_nonzero_exit_code_captured(self) -> None:
        returncode, _, _ = await run_subprocess(["false"])
        assert returncode != 0
