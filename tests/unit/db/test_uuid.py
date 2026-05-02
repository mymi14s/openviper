import uuid
from unittest.mock import MagicMock

import sqlalchemy as sa
from sqlalchemy.sql.sqltypes import Uuid

from openviper.db.executor import _apply_lookup


def test_apply_lookup_uuid_native():
    """Test that _apply_lookup preserves uuid.UUID for UUID columns."""
    col = MagicMock()
    col.type = Uuid(as_uuid=True)

    val = uuid.uuid4()
    _apply_lookup(col, "exact", val)

    # result should be a binary expression (col == val)
    # Since col is a Mock, we check if it was compared with the native UUID
    col.__eq__.assert_called_once_with(val)


def test_apply_lookup_uuid_string_conversion():
    """Test that _apply_lookup converts strings to uuid.UUID for UUID columns."""
    col = MagicMock()
    col.type = Uuid(as_uuid=True)

    val_str = str(uuid.uuid4())
    val_uuid = uuid.UUID(val_str)

    _apply_lookup(col, "exact", val_str)

    col.__eq__.assert_called_once_with(val_uuid)


def test_apply_lookup_non_uuid_stringification():
    """Test that _apply_lookup still stringifies UUIDs for non-UUID columns."""
    col = MagicMock()
    col.type = sa.String()

    val = uuid.uuid4()
    _apply_lookup(col, "exact", val)

    col.__eq__.assert_called_once_with(str(val))


def test_apply_lookup_uuid_ne():
    """Test that _apply_lookup handles 'ne' lookup for UUID columns."""
    col = MagicMock()
    col.type = Uuid(as_uuid=True)

    val = uuid.uuid4()
    _apply_lookup(col, "ne", val)

    col.__ne__.assert_called_once_with(val)


def test_apply_lookup_uuid_isnull():
    """Test that _apply_lookup handles 'isnull' lookup for UUID columns."""
    col = MagicMock()
    col.type = Uuid(as_uuid=True)

    # isnull=True
    _apply_lookup(col, "isnull", True)
    col.is_.assert_called_once_with(None)

    # isnull=False
    _apply_lookup(col, "isnull", False)
    col.isnot.assert_called_once_with(None)
