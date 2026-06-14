"""Reset global state between unit tests to prevent cross-test pollution."""

from __future__ import annotations

import pytest

from openviper.auth.session.store import reset_store_instance
from openviper.db import connection as db_connection
from openviper.db.connections import connections


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
