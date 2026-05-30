"""Virtual model backend contracts, database backend API, and registries."""

from openviper.db.backends.api import APIVirtualBackend
from openviper.db.backends.base import VirtualBackend, VirtualBackendCapabilities
from openviper.db.backends.client import DatabaseClient
from openviper.db.backends.creation import DatabaseCreation
from openviper.db.backends.database import DatabaseBackend
from openviper.db.backends.db_registry import (
    DatabaseBackendRegistry,
    database_backend_registry,
    get_database_backend_class,
)
from openviper.db.backends.execution import DatabaseExecution
from openviper.db.backends.features import DatabaseFeatures
from openviper.db.backends.introspection import DatabaseIntrospection
from openviper.db.backends.operations import DatabaseOperations
from openviper.db.backends.registry import BackendRegistry, backend_registry
from openviper.db.backends.sqlalchemy import DefaultDatabaseBackend

__all__ = [
    "APIVirtualBackend",
    "BackendRegistry",
    "DatabaseBackend",
    "DatabaseBackendRegistry",
    "DatabaseClient",
    "DatabaseCreation",
    "DatabaseExecution",
    "DatabaseFeatures",
    "DatabaseIntrospection",
    "DatabaseOperations",
    "DefaultDatabaseBackend",
    "VirtualBackend",
    "VirtualBackendCapabilities",
    "backend_registry",
    "database_backend_registry",
    "get_database_backend_class",
]
