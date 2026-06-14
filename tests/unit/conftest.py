"""Reset global state between unit tests to prevent cross-test pollution."""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from openviper.auth.session.store import reset_store_instance
from openviper.core.management.base import CommandError
from openviper.db import connection as db_connection
from openviper.db.connections import connections


def run_async_coro(coro: t.Coroutine[t.Any, t.Any, t.Any]) -> t.Any:
    """Execute an async coroutine synchronously to avoid RuntimeWarning from un-awaited coroutines.

    Pass this as *side_effect* when mocking ``run_async_command`` so the
    inner coroutine is actually driven to completion instead of being
    garbage-collected while still in the ``created`` state.
    """
    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    except CommandError:
        raise
    except Exception as exc:
        raise CommandError(str(exc)) from exc


@pytest.fixture(autouse=True)
def reset_connections_state() -> None:
    """Reset global singletons before each unit test to prevent cross-test pollution.

    Integration tests (tests/integration/) call ``configure_db()`` which sets
    ``connections.initialized = True``, registers backends in
    ``connections.backends``, and caches a real async engine in
    ``openviper.db.connection._engine``.  That state leaks into subsequent
    unit tests and causes engine lookups to bypass mocked ``get_engine()``
    paths, leading to spurious failures.

    Similarly, ``get_session_store()`` caches its singleton at the module
    level, which can carry a real database connection from integration tests
    into unit tests.

    This fixture runs automatically for every test under ``tests/unit/``.
    """
    was_initialized = connections.initialized
    old_backends = {**connections.backends}
    old_engine = db_connection._engine
    connections.initialized = False
    connections.backends.clear()
    db_connection._engine = None
    reset_store_instance()
    yield
    connections.initialized = was_initialized
    connections.backends.clear()
    connections.backends.update(old_backends)
    db_connection._engine = old_engine
    reset_store_instance()
