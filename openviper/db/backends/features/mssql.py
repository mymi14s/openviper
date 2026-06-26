"""Microsoft SQL Server feature flags."""

from __future__ import annotations

from openviper.db.backends.features.base import DatabaseFeatures


class MSSQLFeatures(DatabaseFeatures):
    """Feature flags for Microsoft SQL Server."""

    supports_returning: bool = True
    supports_partial_indexes: bool = True
    supports_check_constraints: bool = True
    supports_schema_comments: bool = True
