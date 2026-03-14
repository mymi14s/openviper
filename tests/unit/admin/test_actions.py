"""Unit tests for openviper.admin.actions — batch actions system."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openviper.admin.actions import (
    ActionResult,
    AdminAction,
    DeleteSelectedAction,
    _action_registry,
    action,
    get_action,
    get_available_actions,
    register_action,
)
from openviper.http.request import Request


def _make_request(user=None):
    """Create a Request with a mock user attached."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
    }

    async def receive():
        return {"type": "http.disconnect"}

    req = Request(scope, receive)
    req.user = user
    return req


def _make_user(is_authenticated=True, is_superuser=False, is_staff=False):
    """Create a mock user."""
    user = MagicMock()
    user.is_authenticated = is_authenticated
    user.is_superuser = is_superuser
    user.is_staff = is_staff
    user.has_perm = AsyncMock(return_value=True)
    return user


class TestActionResult:
    """Test ActionResult dataclass."""

    def test_success_result(self):
        result = ActionResult(success=True, count=5, message="Done")
        assert result.success is True
        assert result.count == 5
        assert result.message == "Done"
        assert result.errors is None

    def test_result_with_errors(self):
        result = ActionResult(
            success=False, count=0, message="Failed", errors=["Error 1", "Error 2"]
        )
        assert result.success is False
        assert result.count == 0
        assert result.errors == ["Error 1", "Error 2"]


class TestAdminAction:
    """Test AdminAction base class."""

    def test_default_name_from_class(self):
        class CustomAction(AdminAction):
            pass

        action = CustomAction()
        assert action.name == "customaction"

    def test_default_description_from_class(self):
        class CustomAction(AdminAction):
            pass

        action = CustomAction()
        assert action.description == "Customaction"

    def test_custom_name_and_description(self):
        class CustomAction(AdminAction):
            name = "my_action"
            description = "My Custom Action"

        action = CustomAction()
        assert action.name == "my_action"
        assert action.description == "My Custom Action"

    @pytest.mark.asyncio
    async def test_execute_not_implemented(self):
        action = AdminAction()
        queryset = MagicMock()
        request = _make_request()

        with pytest.raises(NotImplementedError, match="Subclasses must implement execute"):
            await action.execute(queryset, request)

    def test_has_permission_no_permissions_required(self):
        action = AdminAction()
        request = _make_request(user=_make_user())
        assert action.has_permission(request) is True

    def test_has_permission_with_permissions_and_superuser(self):
        class ProtectedAction(AdminAction):
            permissions = ["admin.delete"]

        action = ProtectedAction()
        user = _make_user(is_superuser=True)
        request = _make_request(user=user)
        assert action.has_permission(request) is True

    def test_has_permission_no_user(self):
        class ProtectedAction(AdminAction):
            permissions = ["admin.delete"]

        action = ProtectedAction()
        request = _make_request(user=None)
        assert action.has_permission(request) is False

    def test_get_info(self):
        class CustomAction(AdminAction):
            name = "test_action"
            description = "Test Action"
            confirm_message = "Are you sure?"

        action = CustomAction()
        info = action.get_info()

        assert info["name"] == "test_action"
        assert info["description"] == "Test Action"
        assert info["confirm_message"] == "Are you sure?"
        assert info["requires_confirmation"] is True

    def test_get_info_no_confirmation(self):
        action = AdminAction()
        info = action.get_info()
        assert info["requires_confirmation"] is False
        assert info["confirm_message"] is None


class TestDeleteSelectedAction:
    """Test built-in DeleteSelectedAction."""

    def test_attributes(self):
        action = DeleteSelectedAction()
        assert action.name == "delete_selected"
        assert action.description == "Delete selected items"
        assert action.confirm_message is not None

    @pytest.mark.asyncio
    async def test_execute_deletes_objects(self):
        queryset = MagicMock()
        queryset.count = AsyncMock(return_value=3)
        queryset.delete = AsyncMock()
        request = _make_request()

        action = DeleteSelectedAction()
        result = await action.execute(queryset, request)

        assert result.success is True
        assert result.count == 3
        assert "deleted 3 item(s)" in result.message.lower()
        queryset.count.assert_awaited_once()
        queryset.delete.assert_awaited_once()


class TestRegisterAction:
    """Test action registration."""

    def setup_method(self):
        """Clear registry before each test."""
        # Save original registry
        self.original_registry = _action_registry.copy()

    def teardown_method(self):
        """Restore registry after each test."""
        _action_registry.clear()
        _action_registry.update(self.original_registry)

    def test_register_action_class(self):
        class MyAction(AdminAction):
            name = "my_action"

        result = register_action(MyAction)
        assert result is MyAction
        assert "my_action" in _action_registry
        assert _action_registry["my_action"] is MyAction

    def test_register_action_decorator(self):
        @register_action
        class DecoratedAction(AdminAction):
            name = "decorated"

        assert "decorated" in _action_registry
        assert _action_registry["decorated"] is DecoratedAction


class TestGetAction:
    """Test get_action function."""

    def test_get_existing_action(self):
        action = get_action("delete_selected")
        assert action is not None
        assert isinstance(action, DeleteSelectedAction)

    def test_get_nonexistent_action(self):
        action = get_action("nonexistent")
        assert action is None


class TestGetAvailableActions:
    """Test get_available_actions function."""

    def test_get_available_actions_for_staff_user(self):
        user = _make_user(is_staff=True)
        request = _make_request(user=user)
        actions = get_available_actions(request)

        # Should at least have delete_selected
        assert len(actions) > 0
        assert any(a.name == "delete_selected" for a in actions)

    def test_get_available_actions_filters_by_permission(self):
        # Add a protected action temporarily
        class ProtectedAction(AdminAction):
            name = "protected"
            permissions = ["admin.special"]

        _action_registry["protected"] = ProtectedAction

        # User without permissions
        user = _make_user(is_staff=False, is_superuser=False)
        del user.has_perm
        request = _make_request(user=user)
        actions = get_available_actions(request)

        # Should not include protected action
        assert not any(a.name == "protected" for a in actions)

        # Cleanup
        del _action_registry["protected"]


class TestActionDecorator:
    """Test @action decorator."""

    def setup_method(self):
        """Clear registry before each test."""
        self.original_registry = _action_registry.copy()

    def teardown_method(self):
        """Restore registry after each test."""
        _action_registry.clear()
        _action_registry.update(self.original_registry)

    def test_decorator_with_parentheses(self):
        @action(description="Test Action", confirm_message="Are you sure?")
        async def test_action(queryset, request):
            return ActionResult(success=True, count=1, message="Done")

        assert "test_action" in _action_registry
        action_class = _action_registry["test_action"]
        action_instance = action_class()
        assert action_instance.description == "Test Action"
        assert action_instance.confirm_message == "Are you sure?"

    def test_decorator_without_parentheses(self):
        @action
        async def simple_action(queryset, request):
            return ActionResult(success=True, count=0, message="OK")

        assert "simple_action" in _action_registry

    @pytest.mark.asyncio
    async def test_decorated_function_execution(self):
        @action
        async def my_action(queryset, request):
            await queryset.update(status="done")
            return ActionResult(success=True, count=5, message="Updated 5 items")

        action_class = _action_registry["my_action"]
        action_instance = action_class()

        queryset = MagicMock()
        queryset.update = AsyncMock()
        request = _make_request()

        result = await action_instance.execute(queryset, request)

        assert result.success is True
        assert result.count == 5
        assert result.message == "Updated 5 items"
        queryset.update.assert_awaited_once_with(status="done")

    @pytest.mark.asyncio
    async def test_decorated_sync_function(self):
        @action
        def sync_action(queryset, request):
            return 10

        action_class = _action_registry["sync_action"]
        action_instance = action_class()

        queryset = MagicMock()
        request = _make_request()

        result = await action_instance.execute(queryset, request)

        assert result.success is True
        assert result.count == 10

    @pytest.mark.asyncio
    async def test_decorated_function_with_three_params(self):
        """Test function that expects model_admin as first parameter."""

        @action
        async def admin_action(model_admin, queryset, request):
            return ActionResult(success=True, count=1, message="With admin")

        action_class = _action_registry["admin_action"]
        action_instance = action_class()

        queryset = MagicMock()
        request = _make_request()
        model_admin = MagicMock()

        result = await action_instance.execute(queryset, request, model_admin)

        assert result.success is True
        assert result.message == "With admin"

    def test_decorator_with_permissions(self):
        @action(permissions=["admin.delete", "admin.change"])
        async def protected_action(queryset, request):
            return ActionResult(success=True, count=0, message="OK")

        action_class = _action_registry["protected_action"]
        action_instance = action_class()
        assert action_instance.permissions == ["admin.delete", "admin.change"]

    def test_decorator_default_description(self):
        @action
        async def my_custom_action(queryset, request):
            return ActionResult(success=True, count=0, message="OK")

        action_class = _action_registry["my_custom_action"]
        action_instance = action_class()
        assert action_instance.description == "My Custom Action"
