"""Database and virtual model exception types."""


class DatabaseConfigurationError(Exception):
    """Invalid DATABASES or routing configuration."""

    __slots__ = ()


class DatabaseBackendNotFoundError(Exception):
    """Configured backend cannot be imported or found."""

    __slots__ = ()


class DatabaseAliasNotFoundError(Exception):
    """Requested database alias is not configured."""

    __slots__ = ()


class DatabaseReadOnlyError(Exception):
    """Write attempted on read-only database alias."""

    __slots__ = ()


class DatabaseRoutingError(Exception):
    """Router returned invalid alias or routing failed."""

    __slots__ = ()


class DatabaseTransactionRoutingError(Exception):
    """Invalid routing behavior inside a transaction."""

    __slots__ = ()


class DatabaseOperationNotSupportedError(Exception):
    """Backend does not support requested operation."""

    __slots__ = ()


class VirtualModelError(Exception):
    """Base error for virtual model operations."""

    __slots__ = ()


class VirtualBackendNotFoundError(VirtualModelError):
    """Virtual model backend name is not registered."""

    __slots__ = ()


class ReadOnlyVirtualModelError(VirtualModelError):
    """Write operation was attempted on a read-only virtual model."""

    __slots__ = ()


class UnsupportedVirtualQueryError(VirtualModelError):
    """Virtual backend cannot execute the requested query."""

    __slots__ = ()


class VirtualBackendOperationError(VirtualModelError):
    """Virtual backend operation failed."""

    __slots__ = ()


class SingleModelError(Exception):
    """Base error for single model operations."""

    __slots__ = ()


class SingleModelDoesNotExist(SingleModelError):
    """Requested single model instance does not exist."""

    __slots__ = ()


class SingleModelAlreadyExistsError(SingleModelError):
    """A single model instance already exists."""

    __slots__ = ()


class SingleModelDeleteForbiddenError(SingleModelError):
    """Delete was attempted for single model data."""

    __slots__ = ()


class SingleModelDuplicateForbiddenError(SingleModelError):
    """Duplicate was attempted for single model data."""

    __slots__ = ()
