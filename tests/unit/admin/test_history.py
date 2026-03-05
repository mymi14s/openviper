from unittest.mock import MagicMock, patch

import pytest

from openviper.admin.history import (
    ChangeAction,
    ChangeHistory,
    compute_changes,
    get_change_history,
    get_recent_activity,
    log_change,
)


def test_change_action_enum():
    assert ChangeAction.ADD == "add"
    assert ChangeAction.CHANGE == "change"
    assert ChangeAction.DELETE == "delete"


def test_change_history_str():
    history = ChangeHistory(action=ChangeAction.ADD, model_name="TestModel", object_id=1)
    assert str(history) == "add TestModel #1"


def test_get_changed_fields_dict():
    # Empty
    history1 = ChangeHistory(changed_fields=None)
    assert history1.get_changed_fields_dict() == {}

    history2 = ChangeHistory(changed_fields="")
    assert history2.get_changed_fields_dict() == {}

    # Invalid JSON
    history3 = ChangeHistory(changed_fields="{invalid")
    assert history3.get_changed_fields_dict() == {}

    # Valid JSON
    history4 = ChangeHistory(changed_fields='{"field": {"old": 1, "new": 2}}')
    assert history4.get_changed_fields_dict() == {"field": {"old": 1, "new": 2}}


def test_get_for_object():
    with patch("openviper.admin.history.ChangeHistory.objects") as mock_objects:
        mock_filter = MagicMock()
        mock_objects.filter.return_value = mock_filter
        mock_order = MagicMock()
        mock_filter.order_by.return_value = mock_order
        mock_limit = MagicMock()
        mock_order.limit.return_value = mock_limit

        ChangeHistory.get_for_object("TestModel", 1, limit=10)

        mock_objects.filter.assert_called_once_with(model_name="TestModel", object_id=1)
        mock_filter.order_by.assert_called_once_with("-change_time")
        mock_order.limit.assert_called_once_with(10)


@pytest.mark.asyncio
async def test_get_change_history():
    with patch("openviper.admin.history.ChangeHistory.objects") as mock_objects:
        mock_filter = MagicMock()
        mock_objects.filter.return_value = mock_filter
        mock_order = MagicMock()
        mock_filter.order_by.return_value = mock_order
        mock_limit = MagicMock()
        mock_order.limit.return_value = mock_limit

        # Mock .all() as an async method returning a list
        async def mock_all():
            return ["record1"]

        mock_limit.all = mock_all

        result = await get_change_history("TestModel", 1, limit=5)

        mock_objects.filter.assert_called_once_with(model_name="TestModel", object_id=1)
        mock_filter.order_by.assert_called_once_with("-change_time")
        mock_order.limit.assert_called_once_with(5)
        assert result == ["record1"]


@pytest.mark.asyncio
async def test_get_recent_activity():
    with patch("openviper.admin.history.ChangeHistory.objects") as mock_objects:
        mock_order = MagicMock()
        mock_objects.order_by.return_value = mock_order
        mock_limit = MagicMock()
        mock_order.limit.return_value = mock_limit

        async def mock_all():
            return ["act1", "act2"]

        mock_limit.all = mock_all

        result = await get_recent_activity(limit=20)

        mock_objects.order_by.assert_called_once_with("-change_time")
        mock_order.limit.assert_called_once_with(20)
        assert result == ["act1", "act2"]


@pytest.mark.asyncio
async def test_log_change():
    # Test with user object
    user = MagicMock()
    user.id = 42
    user.username = "testuser"

    with patch("openviper.admin.history.ChangeHistory.objects") as mock_objects:

        async def mock_create(**kwargs):
            return ChangeHistory(**kwargs)

        mock_objects.create = mock_create

        changes = {"name": "test"}
        record = await log_change(
            model_name="TestModel",
            object_id=1,
            action=ChangeAction.ADD,
            changes=changes,
            user=user,
            object_repr="Test Obj",
            message="Created",
        )

        assert record.model_name == "TestModel"
        assert record.object_id == 1
        assert record.action == "add"
        assert record.changed_by_id == 42
        assert record.changed_by_username == "testuser"
        assert record.object_repr == "Test Obj"
        assert record.change_message == "Created"
        # json dumps changes
        import json

        assert json.loads(record.changed_fields) == changes

    # Test with user fallback ID/str
    class MinimalUser:
        pk = 99

        def __str__(self):
            return "min_user"

    minimal = MinimalUser()

    with patch("openviper.admin.history.ChangeHistory.objects") as mock_objects:

        async def mock_create(**kwargs):
            return ChangeHistory(**kwargs)

        mock_objects.create = mock_create

        record2 = await log_change(
            model_name="OtherModel",
            object_id=2,
            action="delete",  # Pass string instead of enum
            changes=None,
            user=minimal,
        )

        assert record2.model_name == "OtherModel"
        assert record2.object_id == 2
        assert record2.action == "delete"
        assert record2.changed_by_id == 99
        assert record2.changed_by_username == "min_user"
        assert record2.object_repr == "OtherModel #2"  # Default representation


def test_compute_changes():
    old_data = {"a": 1, "b": 2, "c": 3}
    new_data = {"a": 1, "b": 20, "d": 4}

    changes = compute_changes(old_data, new_data)

    assert "a" not in changes
    assert changes["b"] == {"old": 2, "new": 20}
    assert changes["c"] == {"old": 3, "new": None}
    assert changes["d"] == {"old": None, "new": 4}


def test_compute_changes_skips_sensitive_fields():
    """Line 194: sensitive fields (password, token, etc.) are silently skipped."""
    old_data = {
        "name": "Alice",
        "age": 30,
        "password": "old_hash",
        "token": "old_token",
        "api_key": "old_key",
    }
    new_data = {
        "name": "Bob",
        "age": 31,
        "password": "new_hash",
        "token": "new_token",
        "api_key": "new_key",
    }

    changes = compute_changes(old_data, new_data)

    # Non-sensitive changed fields appear
    assert "name" in changes
    assert "age" in changes
    # Sensitive fields must NOT appear even though they changed
    assert "password" not in changes
    assert "token" not in changes
    assert "api_key" not in changes
