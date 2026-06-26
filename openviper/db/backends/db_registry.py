"""Database backend registry for resolving backend classes by name or import path."""

from __future__ import annotations

import importlib
from collections.abc import Mapping

from openviper.db.backends.database import DatabaseBackend
from openviper.db.backends.sqlalchemy import DefaultDatabaseBackend
from openviper.db.exceptions import DatabaseBackendNotFoundError, DatabaseConfigurationError


class DatabaseBackendRegistry:
    """Register and resolve database backend classes.

    Built-in backends are registered under short names.  Custom
    backends can be resolved from full import paths.
    """

    def __init__(self) -> None:
        self.backends: dict[str, type[DatabaseBackend]] = {}

    def register(self, name: str, backend_cls: type[DatabaseBackend]) -> None:
        """Register a backend class under a short name."""
        if not name:
            raise ValueError("Backend name cannot be empty.")
        if not (isinstance(backend_cls, type) and issubclass(backend_cls, DatabaseBackend)):
            raise TypeError(f"Backend must be a DatabaseBackend subclass, got {backend_cls!r}.")
        self.backends[name] = backend_cls

    def resolve(self, backend_path: str) -> type[DatabaseBackend]:
        """Resolve a backend name or import path to a backend class.

        Checks registered short names first, then attempts to import
        the path as a dotted module path.
        """
        if backend_path in self.backends:
            return self.backends[backend_path]

        if "." in backend_path:
            return self.import_backend(backend_path)

        raise DatabaseBackendNotFoundError(
            f"Database backend '{backend_path}' is not registered and "
            f"does not look like an import path."
        )

    def import_backend(self, import_path: str) -> type[DatabaseBackend]:
        """Import a backend class from a dotted module path.

        Only paths under whitelisted module prefixes are permitted to
        prevent arbitrary code execution from untrusted configuration.
        """
        allowed_prefixes = ("openviper.db.backends.", "openviper.contrib.")
        if not any(import_path.startswith(prefix) for prefix in allowed_prefixes):
            raise DatabaseBackendNotFoundError(
                f"Backend import path '{import_path}' is not in the allowed "
                f"module prefixes: {', '.join(sorted(allowed_prefixes))}."
            )
        try:
            module_path, class_name = import_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            backend_cls = getattr(module, class_name)
        except (ImportError, AttributeError) as exc:
            raise DatabaseBackendNotFoundError(
                f"Could not import database backend '{import_path}': {exc}."
            ) from exc

        if not (isinstance(backend_cls, type) and issubclass(backend_cls, DatabaseBackend)):
            raise DatabaseBackendNotFoundError(
                f"'{import_path}' is not a DatabaseBackend subclass."
            )
        return backend_cls


def get_database_backend_class(config: Mapping[str, object]) -> type[DatabaseBackend]:
    """Return the backend class for a DATABASES alias config.

    If ``BACKEND`` is missing or ``None``, returns the default
    ``DefaultDatabaseBackend``.  Raises ``DatabaseConfigurationError``
    for empty strings or non-string values.
    """
    backend = config.get("BACKEND")

    if backend is None:
        return DefaultDatabaseBackend

    if backend == "":
        raise DatabaseConfigurationError("DATABASES alias BACKEND cannot be an empty string.")

    if not isinstance(backend, str):
        raise DatabaseConfigurationError(
            f"DATABASES alias BACKEND must be a string when provided, got {type(backend).__name__}."
        )

    return database_backend_registry.resolve(backend)


database_backend_registry = DatabaseBackendRegistry()
database_backend_registry.register("sqlalchemy", DefaultDatabaseBackend)
