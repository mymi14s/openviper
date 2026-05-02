import datetime
from unittest.mock import MagicMock

import sqlalchemy as sa

from openviper.db.executor import _apply_lookup
from openviper.db.fields import BooleanField, DateTimeField, IntegerField, UUIDField


def test_apply_lookup_with_boolean_field():
    """Test that BooleanField.to_db is called (converts to 1/0)."""
    col = MagicMock()
    col.type = sa.Boolean()
    field = BooleanField()
    field.name = "is_active"

    # True -> 1
    _apply_lookup(col, "exact", True, field=field)
    col.__eq__.assert_called_with(1)

    # False -> 0
    _apply_lookup(col, "exact", False, field=field)
    col.__eq__.assert_called_with(0)


def test_apply_lookup_with_datetime_field():
    """Test that DateTimeField.to_db is called (handles conversion)."""
    col = MagicMock()
    col.type = sa.DateTime()
    field = DateTimeField()
    field.name = "created_at"

    dt_str = "2024-01-01T12:00:00"
    _apply_lookup(col, "exact", dt_str, field=field)

    # Should be converted to a datetime object
    call_args = col.__eq__.call_args[0][0]
    assert isinstance(call_args, datetime.datetime)

    # If it was converted to aware, ensure the values match in UTC
    if call_args.tzinfo is not None:
        expected_dt = datetime.datetime.fromisoformat(dt_str).replace(tzinfo=datetime.UTC)
        # Handle cases where get_current_timezone might not be UTC in the test environment
        # but the result is always converted to UTC by to_db
        assert call_args.utctimetuple() == expected_dt.utctimetuple()
    else:
        expected_dt = datetime.datetime.fromisoformat(dt_str)
        assert call_args == expected_dt


def test_apply_lookup_with_integer_field_in_lookup():
    """Test that list values are prepared for 'in' lookup."""
    col = MagicMock()
    col.type = sa.Integer()
    field = IntegerField()
    field.name = "age"

    vals = ["10", "20", 30]
    _apply_lookup(col, "in", vals, field=field)

    # values should be converted to ints
    col.in_.assert_called_once_with([10, 20, 30])


def test_apply_lookup_with_uuid_field():
    """Test that UUIDField.to_db is used (returns uuid.UUID)."""
    col = MagicMock()
    # Mocking col.type as sa.sql.sqltypes.Uuid (aliased to Uuid in executor.py)
    from sqlalchemy.sql.sqltypes import Uuid

    col.type = Uuid(as_uuid=True)
    field = UUIDField()
    field.name = "guid"

    import uuid

    val_str = str(uuid.uuid4())
    expected_uuid = uuid.UUID(val_str)

    _apply_lookup(col, "exact", val_str, field=field)

    col.__eq__.assert_called_once_with(expected_uuid)
