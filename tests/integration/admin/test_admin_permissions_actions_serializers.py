"""Integration tests for admin API permissions, serializers, and actions."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from openviper.admin.actions import (
    ActionResult,
    AdminAction,
    DeleteSelectedAction,
    action,
    get_action,
    get_available_actions,
    register_action,
)
from openviper.admin.api.permissions import (
    PermissionChecker,
    check_admin_access,
    check_model_permission,
    check_object_permission,
)
from openviper.admin.api.serializers import (
    ModelDetailSerializer,
    ModelListSerializer,
    serialize_for_detail,
    serialize_for_list,
    serialize_instance,
    serialize_model_info,
    serialize_value,
)

# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------


def _make_request(is_staff=False, is_superuser=False, is_authenticated=True):
    req = MagicMock()
    user = MagicMock()
    user.is_staff = is_staff
    user.is_superuser = is_superuser
    user.is_authenticated = is_authenticated
    req.user = user
    return req


def _make_model():
    model = MagicMock()
    model._app_name = "myapp"
    return model


class TestCheckAdminAccess:
    def test_superuser_has_access(self):
        req = _make_request(is_superuser=True)
        assert check_admin_access(req) is True

    def test_staff_has_access(self):
        req = _make_request(is_staff=True)
        assert check_admin_access(req) is True

    def test_regular_user_no_access(self):
        req = _make_request(is_staff=False, is_superuser=False)
        assert check_admin_access(req) is False

    def test_unauthenticated_no_access(self):
        req = _make_request(is_authenticated=False)
        # Not authenticated
        req.user.is_authenticated = False
        assert check_admin_access(req) is False

    def test_no_user_no_access(self):
        req = MagicMock()
        req.user = None
        assert check_admin_access(req) is False

    def test_missing_user_attr(self):
        req = MagicMock(spec=[])  # no user attr
        req.user = None
        result = check_admin_access(req)
        assert result is False


class TestCheckModelPermission:
    def test_superuser_always_permitted(self):
        req = _make_request(is_superuser=True)
        assert check_model_permission(req, _make_model(), "view") is True

    def test_staff_permitted(self):
        req = _make_request(is_staff=True, is_superuser=False)
        assert check_model_permission(req, _make_model(), "add") is True

    def test_no_user_not_permitted(self):
        req = MagicMock()
        req.user = None
        assert check_model_permission(req, _make_model(), "view") is False

    def test_regular_user_with_has_perm(self):
        req = _make_request(is_staff=False, is_superuser=False)
        req.user.has_perm = MagicMock(return_value=True)
        result = check_model_permission(req, _make_model(), "view")
        # Returns True because has_perm exists
        assert result is True

    def test_regular_user_without_has_perm(self):
        req = _make_request(is_staff=False, is_superuser=False)
        del req.user.has_perm  # remove has_perm
        result = check_model_permission(req, _make_model(), "view")
        assert result is False


class TestCheckObjectPermission:
    def test_superuser_permitted(self):
        req = _make_request(is_superuser=True)
        obj = MagicMock()
        assert check_object_permission(req, obj, "change") is True

    def test_no_user_not_permitted(self):
        req = MagicMock()
        req.user = None
        obj = MagicMock()
        assert check_object_permission(req, obj, "delete") is False

    def test_staff_permitted_via_model_permission(self):
        req = _make_request(is_staff=True)
        obj = MagicMock()
        assert check_object_permission(req, obj, "view") is True


class TestPermissionChecker:
    def test_is_authenticated(self):
        req = _make_request(is_authenticated=True)
        checker = PermissionChecker(req)
        assert checker.is_authenticated is True

    def test_not_authenticated(self):
        req = _make_request(is_authenticated=False)
        req.user.is_authenticated = False
        checker = PermissionChecker(req)
        assert checker.is_authenticated is False

    def test_is_staff(self):
        req = _make_request(is_staff=True)
        checker = PermissionChecker(req)
        assert checker.is_staff is True

    def test_is_superuser(self):
        req = _make_request(is_superuser=True)
        checker = PermissionChecker(req)
        assert checker.is_superuser is True

    def test_has_admin_access_for_superuser(self):
        req = _make_request(is_superuser=True)
        checker = PermissionChecker(req)
        assert checker.has_admin_access is True

    def test_no_admin_access_for_regular(self):
        req = _make_request(is_staff=False, is_superuser=False)
        checker = PermissionChecker(req)
        assert checker.has_admin_access is False

    def test_no_user_not_staff(self):
        req = MagicMock()
        req.user = None
        checker = PermissionChecker(req)
        assert checker.is_staff is False
        assert checker.is_superuser is False
        assert checker.is_authenticated is False

    def test_can_view(self):
        req = _make_request(is_superuser=True)
        checker = PermissionChecker(req)
        assert checker.can_view(_make_model()) is True

    def test_can_add(self):
        req = _make_request(is_staff=True)
        checker = PermissionChecker(req)
        assert checker.can_add(_make_model()) is True

    def test_can_change_object(self):
        req = _make_request(is_superuser=True)
        checker = PermissionChecker(req)
        obj = MagicMock()
        assert checker.can_change(_make_model(), obj) is True

    def test_can_change_model(self):
        req = _make_request(is_superuser=True)
        checker = PermissionChecker(req)
        assert checker.can_change(_make_model()) is True

    def test_can_delete_object(self):
        req = _make_request(is_superuser=True)
        checker = PermissionChecker(req)
        obj = MagicMock()
        assert checker.can_delete(_make_model(), obj) is True

    def test_can_delete_model(self):
        req = _make_request(is_staff=True)
        checker = PermissionChecker(req)
        assert checker.can_delete(_make_model()) is True


# ---------------------------------------------------------------------------
# Serializer tests
# ---------------------------------------------------------------------------


def _make_model_admin(list_display=None, ordering=None):
    ma = MagicMock()
    ma.get_list_display.return_value = list_display or ["name"]
    ma.get_ordering.return_value = ordering or []
    ma.get_model_info.return_value = {"name": "TestModel"}
    return ma


def _make_instance(**kwargs):
    inst = MagicMock()
    inst.id = kwargs.pop("id", 1)
    for k, v in kwargs.items():
        setattr(inst, k, v)
    return inst


class TestSerializeValue:
    def test_none(self):
        assert serialize_value(None) is None

    def test_string(self):
        assert serialize_value("hello") == "hello"

    def test_integer(self):
        assert serialize_value(42) == 42

    def test_float(self):
        assert serialize_value(3.14) == 3.14

    def test_bool(self):
        assert serialize_value(True) is True
        assert serialize_value(False) is False

    def test_datetime(self):
        from datetime import datetime

        dt = datetime(2024, 1, 1, 12, 0, 0)
        assert serialize_value(dt) == dt.isoformat()

    def test_list(self):
        result = serialize_value([1, "two", None])
        assert result == [1, "two", None]

    def test_tuple(self):
        result = serialize_value((1, 2))
        assert result == [1, 2]

    def test_dict(self):
        result = serialize_value({"a": 1, "b": "two"})
        assert result == {"a": 1, "b": "two"}

    def test_uuid(self):
        import uuid

        u = uuid.uuid4()
        result = serialize_value(u)
        assert result == str(u)

    def test_decimal(self):
        from decimal import Decimal

        d = Decimal("3.14")
        result = serialize_value(d)
        assert isinstance(result, float)
        assert abs(result - 3.14) < 0.001

    def test_fallback_str(self):
        class Obj:
            def __str__(self):
                return "custom_str"

        result = serialize_value(Obj())
        assert result == "custom_str"


class TestSerializeInstance:
    def test_basic_serialization(self):
        inst = MagicMock()
        inst.id = 5
        inst.name = "Test"
        inst.__class__._fields = {"name": MagicMock()}

        ma = _make_model_admin(list_display=["name"])
        result = serialize_instance(inst, ma)
        assert result["id"] == 5
        assert result["name"] == "Test"

    def test_include_fields_filter(self):
        inst = MagicMock()
        inst.id = 3
        inst.name = "Included"
        inst.secret = "not included"
        inst.__class__._fields = {"name": MagicMock(), "secret": MagicMock()}

        ma = _make_model_admin()
        result = serialize_instance(inst, ma, include_fields=["name"])
        assert "name" in result
        assert "secret" not in result


class TestSerializeForList:
    def test_includes_list_display_fields(self):
        inst = _make_instance(id=1, title="Test")
        ma = _make_model_admin(list_display=["title"])
        result = serialize_for_list(inst, ma)
        assert result["id"] == 1
        assert result["title"] == "Test"


class TestSerializeForDetail:
    def test_includes_all_model_fields(self):
        inst = MagicMock()
        inst.id = 7
        inst.name = "Detail"
        inst.__class__._fields = {"name": MagicMock()}
        ma = _make_model_admin()
        result = serialize_for_detail(inst, ma)
        assert result["id"] == 7
        assert result["name"] == "Detail"


class TestSerializeModelInfo:
    def test_returns_model_info(self):
        ma = _make_model_admin()
        result = serialize_model_info(ma)
        assert result == {"name": "TestModel"}


class TestModelListSerializer:
    def test_serializes_list(self):
        instances = [_make_instance(id=1, title="A"), _make_instance(id=2, title="B")]
        for inst in instances:
            inst.__class__._fields = {}
        ma = _make_model_admin(list_display=["title"])
        serializer = ModelListSerializer(ma)
        result = serializer.serialize(instances)
        assert len(result) == 2


class TestModelDetailSerializer:
    def test_serializes_detail(self):
        inst = MagicMock()
        inst.id = 10
        inst.__class__._fields = {}
        ma = _make_model_admin()
        serializer = ModelDetailSerializer(ma)
        result = serializer.serialize(inst)
        assert result["id"] == 10


# ---------------------------------------------------------------------------
# Admin actions tests
# ---------------------------------------------------------------------------


class TestAdminActionBase:
    def test_action_result_dataclass(self):
        result = ActionResult(success=True, count=5, message="Done", errors=None)
        assert result.success is True
        assert result.count == 5
        assert result.message == "Done"
        assert result.errors is None

    def test_action_result_with_errors(self):
        result = ActionResult(success=False, count=0, message="Failed", errors=["err1"])
        assert result.errors == ["err1"]

    def test_admin_action_default_name(self):
        class MyCustomAction(AdminAction):
            async def execute(self, queryset, request, model_admin=None):
                return ActionResult(success=True, count=0, message="ok")

        a = MyCustomAction()
        assert a.name == "mycustomaction"

    def test_admin_action_custom_name(self):
        class MyAction(AdminAction):
            name = "custom_name"

            async def execute(self, queryset, request, model_admin=None):
                return ActionResult(success=True, count=0, message="ok")

        a = MyAction()
        assert a.name == "custom_name"

    def test_action_get_info(self):
        class MyAction(AdminAction):
            name = "test_action"
            description = "A test action"
            confirm_message = "Are you sure?"

            async def execute(self, queryset, request, model_admin=None):
                return ActionResult(success=True, count=0, message="ok")

        a = MyAction()
        info = a.get_info()
        assert info["name"] == "test_action"
        assert info["description"] == "A test action"
        assert info["confirm_message"] == "Are you sure?"
        assert info["requires_confirmation"] is True

    def test_action_execute_raises_not_implemented(self):
        import asyncio

        import pytest

        class IncompleteAction(AdminAction):
            pass

        a = IncompleteAction()
        with pytest.raises(NotImplementedError):
            asyncio.run(a.execute(None, None))

    def test_has_permission_no_required_perms(self):
        class OpenAction(AdminAction):
            permissions = []

            async def execute(self, queryset, request, model_admin=None):
                return ActionResult(success=True, count=0, message="ok")

        a = OpenAction()
        req = _make_request()
        assert a.has_permission(req) is True

    def test_has_permission_no_user(self):
        class ProtectedAction(AdminAction):
            permissions = ["admin.view"]

            async def execute(self, queryset, request, model_admin=None):
                return ActionResult(success=True, count=0, message="ok")

        a = ProtectedAction()
        req = MagicMock()
        req.user = None
        assert a.has_permission(req) is False

    def test_has_permission_superuser_no_has_perm(self):
        class ProtectedAction(AdminAction):
            permissions = ["some.perm"]

            async def execute(self, queryset, request, model_admin=None):
                return ActionResult(success=True, count=0, message="ok")

        a = ProtectedAction()
        req = _make_request(is_superuser=True)
        del req.user.has_perm
        assert a.has_permission(req) is True


class TestDeleteSelectedAction:
    @pytest.mark.asyncio
    async def test_execute_deletes_queryset(self):
        from unittest.mock import AsyncMock

        qs = MagicMock()
        qs.count = AsyncMock(return_value=3)
        qs.delete = AsyncMock()

        action_obj = DeleteSelectedAction()
        req = _make_request()
        result = await action_obj.execute(qs, req)

        assert result.success is True
        assert result.count == 3
        qs.delete.assert_awaited_once()

    def test_has_confirm_message(self):
        a = DeleteSelectedAction()
        assert a.confirm_message is not None
        assert "delete" in a.confirm_message.lower()


class TestGetAction:
    def test_get_delete_selected(self):
        a = get_action("delete_selected")
        assert a is not None
        assert a.name == "delete_selected"

    def test_get_nonexistent(self):
        assert get_action("no_such_action") is None


class TestRegisterAction:
    def test_register_and_retrieve(self):
        class NewAction(AdminAction):
            name = "integration_test_action_xyz"
            description = "Test"

            async def execute(self, queryset, request, model_admin=None):
                return ActionResult(success=True, count=0, message="ok")

        register_action(NewAction)
        found = get_action("integration_test_action_xyz")
        assert found is not None
        assert found.name == "integration_test_action_xyz"


class TestGetAvailableActions:
    def test_returns_list_of_actions(self):
        req = _make_request(is_superuser=True)
        actions = get_available_actions(req)
        assert isinstance(actions, list)
        assert len(actions) >= 1  # At least delete_selected


class TestActionDecorator:
    def test_decorator_with_args(self):
        @action(description="My action", confirm_message="Confirm?")
        async def my_func_action(queryset, request):
            return ActionResult(success=True, count=1, message="Done")

        instance = my_func_action()
        assert instance.description == "My action"
        assert instance.confirm_message == "Confirm?"

    def test_decorator_without_parentheses(self):
        @action
        async def bare_action(queryset, request):
            return ActionResult(success=True, count=0, message="ok")

        instance = bare_action()
        assert hasattr(instance, "execute")

    @pytest.mark.asyncio
    async def test_decorated_action_execute(self):

        @action(description="Test exec")
        async def exec_action(queryset, request):
            return ActionResult(success=True, count=5, message="Executed")

        qs = MagicMock()
        req = _make_request()
        instance = exec_action()
        result = await instance.execute(qs, req)
        assert result.success is True
        assert result.count == 5

    @pytest.mark.asyncio
    async def test_decorated_action_returns_int(self):
        """Action returning int gets wrapped in ActionResult."""

        @action(description="Int return")
        async def count_action(queryset, request):
            return 7

        qs = MagicMock()
        req = _make_request()
        instance = count_action()
        result = await instance.execute(qs, req)
        assert result.success is True
        assert result.count == 7
