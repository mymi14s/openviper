"""Oracle Database feature flags."""

from __future__ import annotations

from openviper.db.backends.features.base import DatabaseFeatures


class OracleFeatures(DatabaseFeatures):
    """Feature flags for Oracle Database."""

    supports_returning: bool = True
    supports_partial_indexes: bool = False
    supports_check_constraints: bool = True
    supports_schema_comments: bool = True
