"""PostgreSQL feature flags."""

from __future__ import annotations

from openviper.db.backends.features.base import DatabaseFeatures


class PostgreSQLFeatures(DatabaseFeatures):
    """Feature flags for PostgreSQL and compatible dialects."""

    supports_returning: bool = True
    supports_partial_indexes: bool = True
    supports_check_constraints: bool = True
    supports_schema_comments: bool = True
