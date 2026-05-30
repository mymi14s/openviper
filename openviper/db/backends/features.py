"""Database feature flags for backend capability detection."""

from __future__ import annotations


class DatabaseFeatures:
    """Declares database capabilities for a configured backend alias.

    The ORM, migrations, admin, and testing layers consult these flags
    to decide which operations are safe to emit against the current
    database.  Concrete backends override individual flags to match
    their dialect's actual support.
    """

    supports_transactions: bool = True
    supports_savepoints: bool = True
    supports_json: bool = True
    supports_uuid: bool = True
    supports_returning: bool = True
    supports_bulk_insert: bool = True
    supports_foreign_keys: bool = True
    supports_indexes: bool = True
    supports_partial_indexes: bool = True
    supports_check_constraints: bool = True
    supports_schema_comments: bool = False
    supports_read_only_connections: bool = False
