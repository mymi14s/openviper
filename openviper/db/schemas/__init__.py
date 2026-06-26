"""JSON-based schema synchronization system.
Per-model JSON schema files that are diffed against the live database at migrate time.
"""

from __future__ import annotations

from openviper.db.schemas.detect import detect_changes, match_renames
from openviper.db.schemas.introspect import introspect_db_schema
from openviper.db.schemas.json_reader import (
    discover_json_schemas,
    read_all_raw_schemas,
    read_json_schema,
)
from openviper.db.schemas.json_writer import delete_json_schema, write_json_schema
from openviper.db.schemas.sync import SchemaSync
from openviper.db.schemas.validate import validate_type_change

__all__ = [
    "SchemaSync",
    "detect_changes",
    "discover_json_schemas",
    "delete_json_schema",
    "introspect_db_schema",
    "match_renames",
    "read_all_raw_schemas",
    "read_json_schema",
    "validate_type_change",
    "write_json_schema",
]
