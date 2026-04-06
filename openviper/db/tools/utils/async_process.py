"""Async subprocess execution helpers for database CLI tools."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from openviper.db.tools.utils.validators import ValidationError, validate_subprocess_arg

_DEFAULT_TIMEOUT: int = 3600


async def run_subprocess(
    args: Sequence[str],
    *,
    timeout: int = _DEFAULT_TIMEOUT,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Execute a subprocess without a shell and stream its output.

    Each argument in *args* is validated to reject shell meta-characters
    before the process is launched.

    Args:
        args: The command and its arguments as a sequence of strings.
        timeout: Maximum seconds to wait before raising
            :exc:`asyncio.TimeoutError`.
        env: Optional environment mapping to pass to the child process.
            When ``None`` the current process environment is inherited.

    Returns:
        A 3-tuple of ``(returncode, stdout, stderr)``.

    Raises:
        ValidationError: When any argument contains unsafe characters.
        asyncio.TimeoutError: When the process exceeds *timeout* seconds.
        OSError: When the executable is not found or cannot be launched.
    """
    validated: list[str] = []
    for i, arg in enumerate(args):
        validated.append(validate_subprocess_arg(arg, label=f"args[{i}]"))

    proc = await asyncio.create_subprocess_exec(
        *validated,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise

    returncode = proc.returncode or 0
    return (
        returncode,
        stdout_bytes.decode("utf-8", errors="replace"),
        stderr_bytes.decode("utf-8", errors="replace"),
    )


def check_returncode(
    returncode: int,
    stderr: str,
    *,
    command: str,
) -> None:
    """Raise :exc:`RuntimeError` when *returncode* indicates failure.

    Args:
        returncode: Process exit code.
        stderr: Captured standard error output.
        command: Human-readable command name for the error message.

    Raises:
        RuntimeError: When *returncode* is non-zero.
    """
    if returncode != 0:
        raise RuntimeError(
            f"{command} failed with exit code {returncode}. stderr: {stderr.strip()}"
        )


__all__ = [
    "ValidationError",
    "check_returncode",
    "run_subprocess",
]
