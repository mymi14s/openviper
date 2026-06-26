import uuid
from unittest.mock import MagicMock

import sqlalchemy as sa
from sqlalchemy.sql.sqltypes import Uuid

from openviper.db.executor import apply_lookup


def test_apply_lookup_uuid_native():
    """Test that apply_lookup preserves uuid.UUID for UUID columns."""
    col = MagicMock()
    col.type = Uuid(as_uuid=True)

    val = uuid.uuid4()
    apply_lookup(col, "exact", val)

    # result should be a binary expression (col == val)
    # Since col is a Mock, we check if it was compared with the native UUID
    col.__eq__.assert_called_once_with(val)


def test_apply_lookup_uuid_string_conversion():
    """Test that apply_lookup converts strings to uuid.UUID for UUID columns."""
    col = MagicMock()
    col.type = Uuid(as_uuid=True)

    val_str = str(uuid.uuid4())
    val_uuid = uuid.UUID(val_str)

    apply_lookup(col, "exact", val_str)

    col.__eq__.assert_called_once_with(val_uuid)


def test_apply_lookup_non_uuid_stringification():
    """Test that apply_lookup still stringifies UUIDs for non-UUID columns."""
    col = MagicMock()
    col.type = sa.String()

    val = uuid.uuid4()
    apply_lookup(col, "exact", val)

    col.__eq__.assert_called_once_with(str(val))


def test_apply_lookup_uuid_ne():
    """Test that apply_lookup handles 'ne' lookup for UUID columns."""
    col = MagicMock()
    col.type = Uuid(as_uuid=True)

    val = uuid.uuid4()
    apply_lookup(col, "ne", val)

    col.__ne__.assert_called_once_with(val)


def test_apply_lookup_uuid_isnull():
    """Test that apply_lookup handles 'isnull' lookup for UUID columns."""
    col = MagicMock()
    col.type = Uuid(as_uuid=True)

    # isnull=True
    apply_lookup(col, "isnull", True)
    col.is_.assert_called_once_with(None)

    # isnull=False
    apply_lookup(col, "isnull", False)
    col.isnot.assert_called_once_with(None)


def test_apply_lookup_uuid_in_with_strings():
    """Test that apply_lookup converts string list items to uuid.UUID for 'in' lookup."""
    col = MagicMock()
    col.type = Uuid(as_uuid=True)

    u1 = uuid.uuid4()
    u2 = uuid.uuid4()
    val_list = [str(u1), str(u2)]

    apply_lookup(col, "in", val_list)

    col.in_.assert_called_once()
    actual = col.in_.call_args[0][0]
    assert list(actual) == [u1, u2]


def test_apply_lookup_uuid_in_with_mixed_types():
    """Test that apply_lookup handles mixed UUID/string items in 'in' lookup."""
    col = MagicMock()
    col.type = Uuid(as_uuid=True)

    u1 = uuid.uuid4()
    u2 = uuid.uuid4()
    val_list = [u1, str(u2)]

    apply_lookup(col, "in", val_list)

    col.in_.assert_called_once()
    actual = col.in_.call_args[0][0]
    assert list(actual) == [u1, u2]


def test_apply_lookup_uuid_not_in_with_strings():
    """Test that apply_lookup converts string list items to uuid.UUID for 'not_in' lookup."""
    col = MagicMock()
    col.type = Uuid(as_uuid=True)

    u1 = uuid.uuid4()
    u2 = uuid.uuid4()
    val_list = [str(u1), str(u2)]

    apply_lookup(col, "not_in", val_list)

    col.notin_.assert_called_once()
    actual = col.notin_.call_args[0][0]
    assert list(actual) == [u1, u2]
