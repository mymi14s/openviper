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


def test_action_result():
    res = ActionResult(success=True, count=5, message="Done")
    assert res.success is True
    assert res.count == 5
    assert res.message == "Done"
    assert res.errors is None


def test_admin_action_base():
    class CustomAction(AdminAction):
        pass

    act = CustomAction()
    assert act.name == "customaction"
    assert act.description == "Customaction"
    assert act.confirm_message is None
    assert act.permissions == []

    import asyncio

    with pytest.raises(NotImplementedError):
        asyncio.run(act.execute(MagicMock(), MagicMock()))

    # permissions test
    mock_request = MagicMock()
    assert act.has_permission(mock_request) is True

    act.permissions = ["some_perm"]
    mock_request.user = None
    assert act.has_permission(mock_request) is False

    mock_request.user = MagicMock()
    del mock_request.user.has_perm
    mock_request.user.is_superuser = True
    assert act.has_permission(mock_request) is True

    mock_request.user.is_superuser = False
    assert act.has_permission(mock_request) is False

    info = act.get_info()
    assert info["name"] == "customaction"
    assert info["description"] == "Customaction"
    assert info["requires_confirmation"] is False


@pytest.mark.asyncio
async def test_delete_selected_action():
    act = DeleteSelectedAction()
    assert act.name == "delete_selected"

    # mock queryset
    qs = MagicMock()
    qs.count = AsyncMock(return_value=3)
    qs.delete = AsyncMock()

    res = await act.execute(qs, MagicMock())
    assert res.success is True
    assert res.count == 3
    assert "deleted 3" in res.message
    qs.count.assert_called_once()
    qs.delete.assert_called_once()


def test_register_and_get_action():
    class TestRegisterAction(AdminAction):
        name = "test_reg"

    register_action(TestRegisterAction)

    got = get_action("test_reg")
    assert isinstance(got, TestRegisterAction)

    assert get_action("non_existent") is None

    # test available actions
    mock_req = MagicMock()
    mock_req.user = MagicMock()

    actions = get_available_actions(mock_req)
    # Should at least contain delete_selected and test_reg
    action_names = [a.name for a in actions]
    assert "delete_selected" in action_names
    assert "test_reg" in action_names


@pytest.mark.asyncio
async def test_action_decorator_args_2():
    # Decorator as a function without parentheses
    @action
    def simple_action(queryset, request):
        return ActionResult(success=True, count=2, message="Simple")

    assert "simple_action" in _action_registry

    act_instance = get_action("simple_action")
    res = await act_instance.execute(MagicMock(), MagicMock())
    assert res.count == 2
    assert res.message == "Simple"


@pytest.mark.asyncio
async def test_action_decorator_args_3_and_awaitable():
    @action(description="Async Act", confirm_message="Sure?", permissions=["test"])
    async def async_action(model_admin, queryset, request):
        return 10  # Returns count instead of ActionResult directly

    act_instance = get_action("async_action")
    assert act_instance.description == "Async Act"
    assert act_instance.confirm_message == "Sure?"
    assert act_instance.permissions == ["test"]

    res = await act_instance.execute(MagicMock(), MagicMock(), MagicMock())
    assert res.success is True
    assert res.count == 10
    assert "successfully" in res.message


@pytest.mark.asyncio
async def test_action_decorator_no_count():
    @action
    def no_count_action(queryset, request):
        return "Not an int"

    act_instance = get_action("no_count_action")
    res = await act_instance.execute(MagicMock(), MagicMock())
    assert res.success is True
    assert res.count == 0


def test_admin_action_has_permission_with_has_perm_user():
    """Line 92: user has has_perm attr → for loop completes → return True."""

    class CustomAction(AdminAction):
        pass

    act = CustomAction()
    act.permissions = ["some_perm"]

    mock_request = MagicMock()
    mock_user = MagicMock()
    # User HAS has_perm → the branch inside the loop is skipped
    mock_user.has_perm = MagicMock(return_value=True)
    mock_request.user = mock_user

    assert act.has_permission(mock_request) is True
