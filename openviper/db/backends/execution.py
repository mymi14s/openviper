"""Database execution hook layer for instrumentation and retries."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger(__name__)


class DatabaseExecution:
    """Execution hook layer for instrumentation, logging, retries, and tracing.

    Subclass and override ``pre_execute``, ``post_execute``, or
    ``on_error`` to add metrics, tracing spans, retry policies, or
    custom error mapping.
    """

    async def pre_execute(
        self,
        statement: sa.Executable,
        parameters: Mapping[str, Any] | None = None,
    ) -> None:
        """Called before a statement is executed.

        Use for timing start, tracing span creation, or audit logging.
        """

    async def post_execute(
        self,
        statement: sa.Executable,
        parameters: Mapping[str, Any] | None = None,
        duration: float | None = None,
    ) -> None:
        """Called after a statement completes successfully.

        *duration* is wall-clock seconds between pre_execute and
        post_execute when the default ``execute`` implementation is used.
        """

    async def on_error(
        self,
        statement: sa.Executable,
        parameters: Mapping[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        """Called when statement execution raises an exception.

        Use for error metrics, alerting, or custom error mapping.
        """

    async def execute(
        self,
        connection: AsyncConnection,
        statement: sa.Executable,
        parameters: Mapping[str, Any] | None = None,
    ) -> Any:
        """Execute a SQLAlchemy statement through the hook lifecycle.

        Calls ``pre_execute``, runs the statement, then calls
        ``post_execute``.  On failure, calls ``on_error`` and
        re-raises.
        """
        await self.pre_execute(statement, parameters)
        start = time.monotonic()
        try:
            if parameters is not None:
                result = await connection.execute(statement, parameters)
            else:
                result = await connection.execute(statement)
        except Exception as exc:
            await self.on_error(statement, parameters, exc)
            raise
        duration = time.monotonic() - start
        await self.post_execute(statement, parameters, duration=duration)
        return result
