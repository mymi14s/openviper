"""Unit tests for openviper.admin.history — change history tracking."""

import datetime
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.admin.history import (
    SENSITIVE_FIELDS,
    ChangeAction,
    ChangeHistory,
    compute_changes,
    get_change_history,
    get_recent_activity,
    log_change,
)


class TestChangeAction:
    """Test ChangeAction enum."""

    def test_enum_values(self):
        assert ChangeAction.ADD == "add"
        assert ChangeAction.CHANGE == "change"
        assert ChangeAction.DELETE == "delete"

    def test_is_string_enum(self):
        # ChangeAction is a StrEnum, should be string-compatible
        assert str(ChangeAction.ADD) == "add"
        assert ChangeAction.CHANGE == "change"


class TestChangeHistory:
    """Test ChangeHistory model."""

    def test_str_representation(self):
        history = ChangeHistory(
            model_name="User", object_id=123, action="change", object_repr="User #123"
        )
        result = str(history)
        assert "change" in result
        assert "User" in result
        assert "123" in result

    def test_get_changed_fields_dict_empty(self):
        history = ChangeHistory(
            model_name="User",
            object_id=123,
            action="change",
            object_repr="User #123",
            changed_fields=None,
        )
        result = history.get_changed_fields_dict()
        assert result == {}

    def test_get_changed_fields_dict_valid_json(self):
        changes = {"username": {"old": "john", "new": "jane"}}
        history = ChangeHistory(
            model_name="User",
            object_id=123,
            action="change",
            object_repr="User #123",
            changed_fields=json.dumps(changes),
        )
        result = history.get_changed_fields_dict()
        assert result == changes

    def test_get_changed_fields_dict_invalid_json(self):
        history = ChangeHistory(
            model_name="User",
            object_id=123,
            action="change",
            object_repr="User #123",
            changed_fields="invalid json{",
        )
        result = history.get_changed_fields_dict()
        assert result == {}

    def test_get_for_object_returns_queryset(self):
        """Test get_for_object class method."""
        queryset = ChangeHistory.get_for_object("User", 123)
        assert queryset is not None

    def test_get_for_object_with_custom_limit(self):
        """Test get_for_object with custom limit."""
        queryset = ChangeHistory.get_for_object("User", 123, limit=10)
        assert queryset is not None


class TestLogChange:
    """Test log_change function."""

    @pytest.mark.asyncio
    async def test_log_add_action(self):
        """Test logging an add action."""
        with patch.object(ChangeHistory.objects, "create", new=AsyncMock()) as mock_create:
            mock_create.return_value = ChangeHistory(
                model_name="User",
                object_id=1,
                action="add",
                object_repr="User #1",
            )

            await log_change("User", 1, ChangeAction.ADD, user=None)

            mock_create.assert_awaited_once()
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["model_name"] == "User"
            assert call_kwargs["object_id"] == "1"
            assert call_kwargs["action"] == "add"

    @pytest.mark.asyncio
    async def test_log_change_with_user(self):
        """Test logging a change with user information."""
        user = MagicMock()
        user.id = 42
        user.username = "admin"

        with patch.object(ChangeHistory.objects, "create", new=AsyncMock()) as mock_create:
            mock_create.return_value = ChangeHistory(
                model_name="Post",
                object_id=10,
                action="change",
                object_repr="Post #10",
                changed_by_id="42",
                changed_by_username="admin",
            )

            await log_change("Post", 10, "change", user=user)

            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["changed_by_id"] == "42"
            assert call_kwargs["changed_by_username"] == "admin"

    @pytest.mark.asyncio
    async def test_log_change_with_changes_dict(self):
        """Test logging changes with field modifications."""
        changes = {"title": {"old": "Old Title", "new": "New Title"}}

        with patch.object(ChangeHistory.objects, "create", new=AsyncMock()) as mock_create:
            mock_create.return_value = ChangeHistory(
                model_name="Post",
                object_id=5,
                action="change",
                object_repr="Post #5",
                changed_fields=json.dumps(changes, default=str),
            )

            await log_change("Post", 5, ChangeAction.CHANGE, changes=changes)

            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["changed_fields"] is not None
            loaded = json.loads(call_kwargs["changed_fields"])
            assert loaded["title"]["new"] == "New Title"

    @pytest.mark.asyncio
    async def test_log_change_with_message(self):
        """Test logging with a custom message."""
        with patch.object(ChangeHistory.objects, "create", new=AsyncMock()) as mock_create:
            mock_create.return_value = ChangeHistory(
                model_name="User",
                object_id=1,
                action="delete",
                object_repr="User #1",
                change_message="Deleted by admin",
            )

            await log_change("User", 1, ChangeAction.DELETE, message="Deleted by admin")

            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["change_message"] == "Deleted by admin"

    @pytest.mark.asyncio
    async def test_log_change_with_custom_object_repr(self):
        """Test logging with custom object representation."""
        with patch.object(ChangeHistory.objects, "create", new=AsyncMock()) as mock_create:
            mock_create.return_value = ChangeHistory(
                model_name="User",
                object_id=1,
                action="add",
                object_repr="Admin User",
            )

            await log_change("User", 1, ChangeAction.ADD, object_repr="Admin User")

            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["object_repr"] == "Admin User"

    @pytest.mark.asyncio
    async def test_log_change_default_object_repr(self):
        """Test that default object repr is generated."""
        with patch.object(ChangeHistory.objects, "create", new=AsyncMock()) as mock_create:
            mock_create.return_value = ChangeHistory(
                model_name="User",
                object_id=99,
                action="add",
                object_repr="User #99",
            )

            await log_change("User", 99, ChangeAction.ADD)

            call_kwargs = mock_create.call_args[1]
            assert "User" in call_kwargs["object_repr"]
            assert "99" in call_kwargs["object_repr"]

    @pytest.mark.asyncio
    async def test_log_change_user_id_coerced_to_str(self):
        """Test that integer user IDs are coerced to strings for VARCHAR column."""
        user = MagicMock()
        user.id = None
        user.pk = 100
        user.username = "testuser"

        with patch.object(ChangeHistory.objects, "create", new=AsyncMock()) as mock_create:
            mock_create.return_value = ChangeHistory(
                model_name="Post",
                object_id=1,
                action="add",
                object_repr="Post #1",
                changed_by_id="100",
            )

            await log_change("Post", 1, ChangeAction.ADD, user=user)

            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["changed_by_id"] == "100"


class TestGetChangeHistory:
    """Test get_change_history function."""

    @pytest.mark.asyncio
    async def test_get_change_history(self):
        """Test retrieving change history for an object."""
        mock_queryset = MagicMock()
        mock_queryset.filter.return_value = mock_queryset
        mock_queryset.order_by.return_value = mock_queryset
        mock_queryset.limit.return_value = mock_queryset
        mock_queryset.all = AsyncMock(return_value=[])

        with patch.object(ChangeHistory, "objects", mock_queryset):
            await get_change_history("User", 123)

            mock_queryset.filter.assert_called_once()
            mock_queryset.order_by.assert_called_once_with("-change_time")

    @pytest.mark.asyncio
    async def test_get_change_history_with_custom_limit(self):
        """Test with custom limit parameter."""
        mock_queryset = MagicMock()
        mock_queryset.filter.return_value = mock_queryset
        mock_queryset.order_by.return_value = mock_queryset
        mock_queryset.limit.return_value = mock_queryset
        mock_queryset.all = AsyncMock(return_value=[])

        with patch.object(ChangeHistory, "objects", mock_queryset):
            await get_change_history("User", 123, limit=100)

            mock_queryset.limit.assert_called_once_with(100)


class TestGetRecentActivity:
    """Test get_recent_activity function."""

    @pytest.mark.asyncio
    async def test_get_recent_activity(self):
        """Test retrieving recent activity across all models."""
        mock_queryset = MagicMock()
        mock_queryset.order_by.return_value = mock_queryset
        mock_queryset.limit.return_value = mock_queryset
        mock_queryset.all = AsyncMock(return_value=[])

        with patch.object(ChangeHistory, "objects", mock_queryset):
            await get_recent_activity()

            mock_queryset.order_by.assert_called_once_with("-change_time")
            mock_queryset.limit.assert_called_once_with(20)

    @pytest.mark.asyncio
    async def test_get_recent_activity_with_custom_limit(self):
        """Test with custom limit parameter."""
        mock_queryset = MagicMock()
        mock_queryset.order_by.return_value = mock_queryset
        mock_queryset.limit.return_value = mock_queryset
        mock_queryset.all = AsyncMock(return_value=[])

        with patch.object(ChangeHistory, "objects", mock_queryset):
            await get_recent_activity(limit=50)

            mock_queryset.limit.assert_called_once_with(50)


class TestComputeChanges:
    """Test compute_changes function."""

    def test_compute_changes_basic(self):
        """Test computing basic field changes."""
        old_data = {"name": "John", "age": 30}
        new_data = {"name": "Jane", "age": 30}

        changes = compute_changes(old_data, new_data)

        assert "name" in changes
        assert changes["name"]["old"] == "John"
        assert changes["name"]["new"] == "Jane"
        assert "age" not in changes  # unchanged

    def test_compute_changes_new_field(self):
        """Test adding a new field."""
        old_data = {"name": "John"}
        new_data = {"name": "John", "email": "john@example.com"}

        changes = compute_changes(old_data, new_data)

        assert "email" in changes
        assert changes["email"]["old"] is None
        assert changes["email"]["new"] == "john@example.com"

    def test_compute_changes_filters_sensitive_fields(self):
        """Test that sensitive fields are excluded."""
        old_data = {"name": "John", "password": "old_pass"}
        new_data = {"name": "Jane", "password": "new_pass"}

        changes = compute_changes(old_data, new_data)

        assert "name" in changes
        assert "password" not in changes  # should be filtered

    def test_compute_changes_filters_fields_with_sensitive_substrings(self):
        """Test that fields containing sensitive keywords are filtered."""
        old_data = {
            "name": "John",
            "api_key": "abc123",
            "access_token": "token123",
        }
        new_data = {
            "name": "Jane",
            "api_key": "def456",
            "access_token": "token456",
        }

        changes = compute_changes(old_data, new_data)

        assert "name" in changes
        assert "api_key" not in changes
        assert "access_token" not in changes

    def test_compute_changes_no_changes(self):
        """Test when data hasn't changed."""
        old_data = {"name": "John", "age": 30}
        new_data = {"name": "John", "age": 30}

        changes = compute_changes(old_data, new_data)

        assert not changes

    def test_compute_changes_all_fields_changed(self):
        """Test when all fields have changed."""
        old_data = {"name": "John", "age": 30, "city": "NYC"}
        new_data = {"name": "Jane", "age": 25, "city": "LA"}

        changes = compute_changes(old_data, new_data)

        assert len(changes) == 3
        assert "name" in changes
        assert "age" in changes
        assert "city" in changes

    def test_compute_changes_empty_dicts(self):
        """Test with empty dictionaries."""
        changes = compute_changes({}, {})
        assert not changes

    def test_compute_changes_complex_values(self):
        """Test with complex values like lists and dicts."""
        old_data = {"tags": ["python", "django"], "meta": {"views": 100}}
        new_data = {"tags": ["python", "flask"], "meta": {"views": 150}}

        changes = compute_changes(old_data, new_data)

        assert "tags" in changes
        assert changes["tags"]["old"] == ["python", "django"]
        assert changes["tags"]["new"] == ["python", "flask"]
        assert "meta" in changes

    def test_compute_changes_datetime_aware_vs_naive(self):
        """Test that aware and naive datetimes comparing equal don't produce a false change."""
        dt = datetime.datetime(2024, 1, 15, 10, 30, 0)
        old_data = {"created_at": dt}
        new_data = {"created_at": dt}

        changes = compute_changes(old_data, new_data)

        assert not changes

    def test_compute_changes_datetime_different_values(self):
        """Test that genuinely different datetimes are detected as changes."""
        old_dt = datetime.datetime(2024, 1, 15, 10, 30, 0)
        new_dt = datetime.datetime(2024, 6, 20, 12, 0, 0)
        old_data = {"created_at": old_dt}
        new_data = {"created_at": new_dt}

        changes = compute_changes(old_data, new_data)

        assert "created_at" in changes

    def test_compute_changes_both_empty_values(self):
        """Test that both old and new being empty doesn't create a change."""
        old_data = {"name": None, "description": ""}
        new_data = {"name": "", "description": None}

        changes = compute_changes(old_data, new_data)

        # Both empty equivalents should not show as changes
        assert "name" not in changes
        assert "description" not in changes


class TestSensitiveFields:
    """Test SENSITIVE_FIELDS constant."""

    def test_contains_common_sensitive_fields(self):
        assert "password" in SENSITIVE_FIELDS
        assert "token" in SENSITIVE_FIELDS
        assert "secret" in SENSITIVE_FIELDS
        assert "key" in SENSITIVE_FIELDS
        assert "api_key" in SENSITIVE_FIELDS
        assert "access_token" in SENSITIVE_FIELDS
        assert "refresh_token" in SENSITIVE_FIELDS

    def test_is_set_type(self):
        assert isinstance(SENSITIVE_FIELDS, set)
