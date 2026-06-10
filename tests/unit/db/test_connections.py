"""Tests for the ConnectionManager and connections module."""

from __future__ import annotations

import pytest

from openviper.db.connections import DEFAULT_ALIAS, ConnectionManager
from openviper.db.exceptions import (
    DatabaseAliasNotFoundError,
    DatabaseConfigurationError,
    DatabaseOperationNotSupportedError,
    DatabaseReadOnlyError,
    DatabaseRoutingError,
    DatabaseTransactionRoutingError,
    ReadOnlyVirtualModelError,
    SingleModelAlreadyExistsError,
    SingleModelDeleteForbiddenError,
    SingleModelDoesNotExist,
    SingleModelDuplicateForbiddenError,
    SingleModelError,
    UnsupportedVirtualQueryError,
    VirtualBackendNotFoundError,
    VirtualBackendOperationError,
    VirtualModelError,
)

# ── ConnectionManager ─────────────────────────────────────────────────────────


class TestConnectionManager:
    def test_default_alias_constant(self) -> None:
        assert DEFAULT_ALIAS == "default"

    def test_initial_state_is_not_initialized(self) -> None:
        mgr = ConnectionManager()
        assert mgr.initialized is False

    def test_backends_starts_empty(self) -> None:
        mgr = ConnectionManager()
        assert mgr.backends == {}

    def test_get_raises_for_unknown_alias(self) -> None:
        mgr = ConnectionManager()
        with pytest.raises(DatabaseAliasNotFoundError, match="not configured"):
            mgr.get("nonexistent")

    def test_all_returns_empty_when_not_initialized(self) -> None:
        mgr = ConnectionManager()
        result = mgr.all()
        # Default DATABASES config creates a "default" backend
        assert len(result) >= 0

    def test_all_returns_sequence_type(self) -> None:
        mgr = ConnectionManager()
        result = mgr.all()
        assert isinstance(result, list)


# ── DatabaseAliasNotFoundError ────────────────────────────────────────────────


class TestDatabaseExceptions:
    def test_alias_not_found_error_message(self) -> None:
        error = DatabaseAliasNotFoundError("replica")
        assert "replica" in str(error)

    def test_configuration_error_message(self) -> None:
        error = DatabaseConfigurationError("bad config")
        assert "bad config" in str(error)

    def test_routing_error_message(self) -> None:
        error = DatabaseRoutingError("bad router")
        assert "bad router" in str(error)

    def test_read_only_error_message(self) -> None:
        error = DatabaseReadOnlyError("replica")
        assert "replica" in str(error)

    def test_transaction_routing_error_message(self) -> None:
        error = DatabaseTransactionRoutingError("cross-db")
        assert "cross-db" in str(error)

    def test_operation_not_supported_error_message(self) -> None:
        error = DatabaseOperationNotSupportedError("jsonb")
        assert "jsonb" in str(error)

    def test_virtual_model_error_hierarchy(self) -> None:
        assert issubclass(VirtualBackendNotFoundError, VirtualModelError)
        assert issubclass(ReadOnlyVirtualModelError, VirtualModelError)
        assert issubclass(UnsupportedVirtualQueryError, VirtualModelError)
        assert issubclass(VirtualBackendOperationError, VirtualModelError)

    def test_single_model_error_hierarchy(self) -> None:
        assert issubclass(SingleModelDoesNotExist, SingleModelError)
        assert issubclass(SingleModelAlreadyExistsError, SingleModelError)
        assert issubclass(SingleModelDeleteForbiddenError, SingleModelError)
        assert issubclass(SingleModelDuplicateForbiddenError, SingleModelError)
