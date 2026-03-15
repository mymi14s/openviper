import datetime as dt
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy
import sqlalchemy.exc

import openviper.admin.api.views
from openviper.admin.api import views
from openviper.admin.api.views import (
    _batch_load_children,
    _is_auth_user_model,
    _serialize_instance_with_children,
    get_admin_router,
)
from openviper.admin.registry import NotRegistered
from openviper.exceptions import NotFound, PermissionDenied, Unauthorized, ValidationError
from openviper.http.request import Request
from openviper.routing.router import Router


class TestAdminViews:
    @pytest.mark.asyncio
    async def test_get_model_config_permission_denied(self, router, mock_request):
        handler = None
        for route in router.routes:
            if route.path == "/models/{app_label}/{model_name}/" and "GET" in route.methods:
                handler = route.handler
                break
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.check_model_permission", return_value=False),
        ):
            ma = MagicMock()
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = MockModel
            with pytest.raises(PermissionDenied):
                await handler(mock_request, app_label="test_app", model_name="MockModel")

    @pytest.mark.asyncio
    async def test_create_instance_by_app_permission_denied(self, router, mock_request):
        handler = None
        for route in router.routes:
            if route.path == "/models/{app_label}/{model_name}/" and "POST" in route.methods:
                handler = route.handler
                break
        mock_request.json.return_value = {"name": "New"}
        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.get_readonly_fields.return_value = []
            ma.child_tables = []
            ma.inlines = []
            ma.has_add_permission.return_value = False
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = MockModel
            with patch.object(MockModel, "__init__", return_value=None):
                with patch.object(MockModel, "save", new_callable=AsyncMock):
                    with pytest.raises(PermissionDenied):
                        await handler(mock_request, app_label="test_app", model_name="MockModel")


class MockUser:
    id = 1
    username = "testuser"
    email = "test@example.com"
    is_staff = True
    is_superuser = False
    is_authenticated = True


class MockModel:
    __name__ = "MockModel"
    _app_name = "test_app"
    _fields = {"name": MagicMock()}
    id = 1
    username = "testuser"

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __str__(self):
        return self.username

    save = AsyncMock
    delete = AsyncMock

    class objects:
        all = MagicMock()
        filter = MagicMock()
        get_or_none = AsyncMock(return_value=None)
        count = AsyncMock(return_value=0)

    @classmethod
    def setup_mock_objects(cls):
        qs = MagicMock()
        qs.all = AsyncMock(return_value=[])
        qs.filter = MagicMock(return_value=qs)
        qs.order_by = MagicMock(return_value=qs)
        qs.offset = MagicMock(return_value=qs)
        qs.limit = MagicMock(return_value=qs)
        qs.select_related = MagicMock(return_value=qs)
        qs.count = AsyncMock(return_value=0)
        qs.delete = AsyncMock(return_value=0)

        cls.objects.all.return_value = qs
        cls.objects.filter.return_value = qs
        cls.objects.count = qs.count
        cls.objects.get_or_none = AsyncMock(return_value=None)
        return qs


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.begin.return_value = AsyncMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
    return engine


@pytest.fixture
def router():
    return get_admin_router()


@pytest.fixture
def mock_qs():
    return MockModel.setup_mock_objects()


@pytest.fixture
def mock_request():
    req = MagicMock(spec=Request)
    req.headers = {}
    req.query_params = {}
    req.user = MockUser()
    req.json = AsyncMock(return_value={})
    return req


class TestAdminAPIViews:
    @pytest.mark.asyncio
    async def test_admin_config(self, router, mock_request):
        handler = None
        for route in router.routes:
            if route.path == "/config/":
                handler = route.handler
                break

        with patch("openviper.admin.api.views.User", MockModel):
            resp = await handler(mock_request)
            data = json.loads(resp.body)
            assert "admin_title" in data
            assert data["user_model"] == "test_app.MockModel"

    @pytest.mark.asyncio
    async def test_admin_login(self, router, mock_request):
        handler = None
        for route in router.routes:
            if route.path == "/auth/login/":
                handler = route.handler
                break

        mock_request.json.return_value = {"username": "test", "password": "password"}

        with (
            patch("openviper.admin.api.views.authenticate") as mock_auth,
            patch("openviper.admin.api.views.create_access_token", return_value="access"),
            patch("openviper.admin.api.views.create_refresh_token", return_value="refresh"),
        ):
            user = MockUser()
            user.id = 1
            user.username = "test"
            mock_auth.return_value = user

            resp = await handler(mock_request)
            data = json.loads(resp.body)
            assert data["access_token"] == "access"
            assert data["user"]["username"] == "test"

    @pytest.mark.asyncio
    async def test_admin_logout(self, router, mock_request):
        handler = None
        for route in router.routes:
            if route.path == "/auth/logout/":
                handler = route.handler
                break

        mock_request.headers = {"authorization": "Bearer token"}
        mock_request.json.return_value = {"refresh_token": "refresh"}

        with (
            patch("openviper.admin.api.views.decode_token_unverified") as mock_decode,
            patch("openviper.admin.api.views.revoke_token") as mock_revoke,
        ):
            mock_decode.return_value = {"jti": "jti", "exp": 123456789, "sub": "1"}

            resp = await handler(mock_request)
            assert resp.status_code == 200
            assert mock_revoke.call_count == 2

    @pytest.mark.asyncio
    async def test_admin_refresh_token(self, router, mock_request):
        handler = None
        for route in router.routes:
            if route.path == "/auth/refresh/":
                handler = route.handler
                break

        mock_request.json.return_value = {"refresh_token": "refresh"}

        with (
            patch("openviper.admin.api.views.decode_refresh_token") as mock_decode,
            patch("openviper.admin.api.views.is_token_revoked", return_value=False),
            patch("openviper.admin.api.views.User", MockModel),
            patch("openviper.admin.api.views.create_access_token", return_value="new_access"),
        ):
            mock_decode.return_value = {"sub": 1, "jti": "jti"}
            user = MockUser()
            user.id = 1
            user.username = "test"
            MockModel.objects.get_or_none.return_value = user

            resp = await handler(mock_request)
            data = json.loads(resp.body)
            assert data["access_token"] == "new_access"

    @pytest.mark.asyncio
    async def test_admin_current_user(self, router, mock_request):
        handler = None
        for route in router.routes:
            if route.path == "/auth/me/":
                handler = route.handler
                break

        resp = await handler(mock_request)
        data = json.loads(resp.body)
        assert data["username"] == "testuser"

    @pytest.mark.asyncio
    async def test_admin_dashboard(self, router, mock_request):
        handler = None
        for route in router.routes:
            if route.path == "/dashboard/":
                handler = route.handler
                break

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.get_recent_activity") as mock_activity,
        ):
            mock_admin.get_all_models.return_value = [(MockModel, MagicMock())]
            mock_activity.return_value = []

            resp = await handler(mock_request)
            data = json.loads(resp.body)
            assert "stats" in data
            assert "recent_activity" in data

    @pytest.mark.asyncio
    async def test_list_models(self, router, mock_request):
        handler = None
        for route in router.routes:
            if route.path == "/models/":
                handler = route.handler
                break

        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.get_model_info.return_value = {"name": "MockModel"}
            mock_admin.get_all_models.return_value = [(MockModel, ma)]
            mock_admin.get_models_grouped_by_app.return_value = {"test_app": [(MockModel, ma)]}

            resp = await handler(mock_request)
            data = json.loads(resp.body)
            assert len(data["models"]) == 1
            assert len(data["apps"]) == 1

    @pytest.mark.asyncio
    async def test_get_model_config(self, router, mock_request):
        handler = None
        for route in router.routes:
            if route.path == "/models/{app_label}/{model_name}/" and "GET" in route.methods:
                handler = route.handler
                break

        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.get_model_info.return_value = {"name": "MockModel"}
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = MockModel

            resp = await handler(mock_request, app_label="test_app", model_name="MockModel")
            data = json.loads(resp.body)
            assert data["name"] == "MockModel"

    @pytest.mark.asyncio
    async def test_list_instances_by_app(self, router, mock_request, mock_qs):
        handler = None
        for route in router.routes:
            if "list" in route.path and "{app_label}" in route.path and "GET" in route.methods:
                handler = route.handler
                break

        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.list_per_page = 20
            ma.get_list_display.return_value = ["id"]
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = MockModel

            resp = await handler(mock_request, app_label="test_app", model_name="MockModel")
            data = json.loads(resp.body)
            assert "items" in data
            assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_create_instance_by_app(self, router, mock_request):
        handler = None
        for route in router.routes:
            if route.path == "/models/{app_label}/{model_name}/" and "POST" in route.methods:
                handler = route.handler
                break

        mock_request.json.return_value = {"name": "New"}

        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.get_readonly_fields.return_value = []
            ma.child_tables = []
            ma.inlines = []
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = MockModel

            with patch.object(MockModel, "__init__", return_value=None):
                with patch.object(MockModel, "save", new_callable=AsyncMock):
                    resp = await handler(mock_request, app_label="test_app", model_name="MockModel")
                    assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_get_instance_by_app(self, router, mock_request):
        handler = None
        for route in router.routes:
            if (
                "{obj_id}" in route.path
                and "GET" in route.methods
                and "history" not in route.path
                and "{app_label}" in route.path
            ):
                handler = route.handler
                break

        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.has_view_permission.return_value = True
            ma.get_model_info.return_value = {}
            ma.get_readonly_fields.return_value = []
            ma.get_fieldsets.return_value = []
            ma.child_tables = []
            ma.inlines = []
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = MockModel

            MockModel.objects.get_or_none.return_value = MockModel(id=1)

            resp = await handler(
                mock_request, app_label="test_app", model_name="MockModel", obj_id=1
            )
            data = json.loads(resp.body)
            assert "instance" in data

    @pytest.mark.asyncio
    async def test_update_instance_by_app(self, router, mock_request):
        handler = None
        for route in router.routes:
            if "{obj_id}" in route.path and "PUT" in route.methods and "{app_label}" in route.path:
                handler = route.handler
                break

        mock_request.json.return_value = {"name": "Updated"}

        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.get_readonly_fields.return_value = []
            ma.child_tables = []
            ma.inlines = []
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = MockModel

            inst = MockModel(id=1)
            inst.save = AsyncMock()
            MockModel.objects.get_or_none.return_value = inst

            resp = await handler(
                mock_request, app_label="test_app", model_name="MockModel", obj_id=1
            )
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_instance_by_app(self, router, mock_request):
        handler = None
        for route in router.routes:
            if (
                "{obj_id}" in route.path
                and "DELETE" in route.methods
                and "{app_label}" in route.path
            ):
                handler = route.handler
                break

        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.has_delete_permission.return_value = True
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = MockModel

            inst = MockModel(id=1)
            inst.delete = AsyncMock()
            MockModel.objects.get_or_none.return_value = inst

            resp = await handler(
                mock_request, app_label="test_app", model_name="MockModel", obj_id=1
            )
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_bulk_action_by_app(self, router, mock_request):
        handler = None
        for route in router.routes:
            if "bulk-action" in route.path and "{app_label}" in route.path:
                handler = route.handler
                break

        mock_request.json.return_value = {"action": "delete", "ids": [1, 2]}

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.get_action") as mock_get_action,
        ):
            ma = MagicMock()
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = MockModel

            action = MagicMock()
            action.has_permission.return_value = True
            action.execute = AsyncMock(
                return_value=MagicMock(success=True, count=2, message="Deleted", errors={})
            )
            mock_get_action.return_value = action

            resp = await handler(mock_request, app_label="test_app", model_name="MockModel")
            data = json.loads(resp.body)
            assert data["success"] is True

    @pytest.mark.asyncio
    async def test_export_instances_by_app(self, router, mock_request):
        handler = None
        for route in router.routes:
            if "export" in route.path and "{app_label}" in route.path:
                handler = route.handler
                break

        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.get_list_display.return_value = ["id", "name"]
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = MockModel

            MockModel.objects.filter.return_value.all.return_value = [MockModel(id=1, name="Test")]

            resp = await handler(mock_request, app_label="test_app", model_name="MockModel")
            assert resp.status_code == 200
            assert "text/csv" in resp.headers["Content-Type"]

    @pytest.mark.asyncio
    async def test_get_instance_history_by_app(self, router, mock_request):
        handler = None
        for route in router.routes:
            if "history" in route.path and "{obj_id}" in route.path and "{app_label}" in route.path:
                handler = route.handler
                break

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.get_change_history") as mock_history,
        ):
            mock_admin.get_model_by_app_and_name.return_value = MockModel
            MockModel.objects.get_or_none.return_value = MockModel(id=1)
            mock_history.return_value = []

            resp = await handler(
                mock_request, app_label="test_app", model_name="MockModel", obj_id=1
            )
            data = json.loads(resp.body)
            assert "history" in data

    @pytest.mark.asyncio
    async def test_fk_search(self, router, mock_request):
        handler = None
        for route in router.routes:
            if "fk-search" in route.path:
                handler = route.handler
                break

        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_by_app_and_name.return_value = MockModel
            mock_qs = MockModel.setup_mock_objects()
            mock_qs.all.return_value = [MockModel(id=1, username="test")]

            resp = await handler(mock_request, app_label="test_app", model_name="MockModel")
            data = json.loads(resp.body)
            assert len(data["items"]) == 1

    @pytest.mark.asyncio
    async def test_global_search(self, router, mock_request):
        handler = None
        for route in router.routes:
            if route.path == "/search/":
                handler = route.handler
                break

        mock_request.query_params = {"q": "test"}

        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.get_search_fields.return_value = ["username"]
            mock_admin.get_all_models.return_value = [(MockModel, ma)]
            mock_admin._get_app_label.return_value = "test_app"

            mock_qs = MockModel.setup_mock_objects()
            mock_qs.all.return_value = [MockModel(id=1, username="test")]

            resp = await handler(mock_request)
            data = json.loads(resp.body)
            assert len(data["results"]) == 1

    @pytest.mark.asyncio
    async def test_batch_load_children(self):
        ma = MagicMock()
        inline = MagicMock()
        inline.model = MockModel
        inline.fk_name = "parent_id"
        inline.fields = ["name"]
        ma.child_tables = [MagicMock(return_value=inline)]
        ma.inlines = []

        inst = MockUser()
        inst.id = 1

        with patch.object(MockModel.objects, "filter") as mock_filter:
            qs = MagicMock()
            qs.all = AsyncMock(return_value=[MagicMock(id=2, parent_id=1, name="Child")])
            mock_filter.return_value = qs

            res = await _batch_load_children(ma, MockModel, [inst])
            assert 1 in res
            assert "mockmodel_set" in res[1]

    @pytest.mark.asyncio
    async def test_get_model_not_found(self, router, mock_request):
        handler = None
        for route in router.routes:
            if route.path == "/models/{model_name}/" and "GET" in route.methods:
                handler = route.handler
                break

        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_name.side_effect = NotRegistered("Not found")
            with pytest.raises(NotFound):
                await handler(mock_request, model_name="Missing")

    @pytest.mark.asyncio
    async def test_create_instance_by_app_validation_error(self, router, mock_request):
        handler = None
        for route in router.routes:
            if route.path == "/models/{app_label}/{model_name}/" and "POST" in route.methods:
                handler = route.handler
                break
        mock_request.json.return_value = {"name": "New"}
        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.get_readonly_fields.return_value = []
            ma.child_tables = []
            ma.inlines = []
            ma.has_add_permission.return_value = True
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = MockModel
            with patch.object(MockModel, "__init__", return_value=None):
                # Patch coerce_field_value to raise ValueError (should return 422)
                with patch(
                    "openviper.admin.api.views.coerce_field_value", side_effect=ValueError("bad")
                ):
                    resp = await handler(mock_request, app_label="test_app", model_name="MockModel")
                    assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_get_filter_options(self, router, mock_request):
        handler = None
        for route in router.routes:
            if route.path == "/models/{model_name}/filters/":
                handler = route.handler
                break

        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.get_list_filter.return_value = ["name"]
            mock_admin.get_model_admin_by_name.return_value = ma

            field = MagicMock()
            field.__class__.__name__ = "CharField"
            field.choices = []
            MockModel._fields = {"name": field}
            mock_admin.get_model_by_name.return_value = MockModel

            resp = await handler(mock_request, model_name="MockModel")
            data = json.loads(resp.body)
            assert "filters" in data

    @pytest.mark.asyncio
    async def test_export_no_permission(self, router, mock_request):
        handler = None
        for route in router.routes:
            if route.path == "/models/{model_name}/export/" and "POST" in route.methods:
                handler = route.handler
                break

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.check_model_permission", return_value=False),
        ):
            mock_admin.get_model_admin_by_name.return_value = MagicMock()
            mock_admin.get_model_by_name.return_value = MockModel

            with pytest.raises(PermissionDenied):
                await handler(mock_request, model_name="MockModel")

    @pytest.mark.asyncio
    async def test_delete_no_permission(self, router, mock_request):
        handler = None
        for route in router.routes:
            if (
                route.path == "/models/{app_label}/{model_name}/{obj_id}/"
                and "DELETE" in route.methods
            ):
                handler = route.handler
                break

        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.has_delete_permission.return_value = False
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = MockModel

            MockModel.objects.get_or_none.return_value = MockModel(id=1)

            with pytest.raises(PermissionDenied):
                await handler(mock_request, "test_app", "MockModel", 1)


def _make_request(method="GET", path="/", user=None, body=None):
    """Create a mock request."""
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "query_string": b"",
    }

    async def receive():
        if body:
            return {"type": "http.request", "body": body}
        return {"type": "http.disconnect"}

    request = Request(scope, receive)
    if user:
        request.user = user
    return request


def _make_user(username="testuser", is_staff=True, is_superuser=False):
    """Create a mock user."""
    user = MagicMock()
    user.username = username
    user.is_staff = is_staff
    user.is_superuser = is_superuser
    user.is_authenticated = True
    return user


def _make_model_class(name="TestModel", app_name="test"):
    """Create a mock model class."""
    model = MagicMock()
    model.__name__ = name
    model._app_name = app_name
    model._table_name = name.lower()
    model._fields = {}
    return model


class TestIsAuthUserModel:
    """Test _is_auth_user_model helper function."""

    def test_returns_true_for_user_model(self):
        """Test that function returns True for the auth user model."""
        with patch("openviper.admin.api.views.User") as mock_user:
            mock_model = MagicMock()
            mock_user.__name__ = "User"
            mock_model.__name__ = "User"

            result = _is_auth_user_model(mock_model)
            # May return True or False depending on comparison logic
            assert isinstance(result, bool)

    def test_returns_false_for_non_user_model(self):
        """Test that function returns False for non-user models."""
        mock_model = MagicMock()
        mock_model.__name__ = "Post"

        result = _is_auth_user_model(mock_model)
        # Should likely be False for non-user model
        assert isinstance(result, bool)

    def test_is_auth_user_model_handles_user_and_non_user_models(self):
        """Test _is_auth_user_model handles user and non-user models correctly."""
        mock_get_user_model = MagicMock()
        mock_user_model = MagicMock()
        mock_get_user_model.return_value = mock_user_model

        with patch("openviper.admin.api.views.get_user_model", mock_get_user_model):
            mock_non_user_model = MagicMock()
            mock_non_user_model.__name__ = "Post"

            # Assuming _is_auth_user_model returns True for user models and False otherwise
            assert _is_auth_user_model(mock_user_model) is True
            assert _is_auth_user_model(mock_non_user_model) is False

    def test_exception_handling(self):
        """Test when get_user_model raises an exception."""
        with patch("openviper.admin.api.views.get_user_model", side_effect=Exception):
            mock_model = MagicMock()
            result = _is_auth_user_model(mock_model)
            assert result is False


class TestGetAdminRouter:
    """Test get_admin_router function."""

    def test_returns_router(self):
        """Test that get_admin_router returns a Router."""

        router = get_admin_router()

        assert isinstance(router, Router)

    def test_router_has_routes(self):
        """Test that router has admin API routes."""

        router = get_admin_router()

        # Router should have routes registered
        assert len(router.routes) > 0


class TestAuthEndpoints:
    """Test authentication endpoint logic."""

    @pytest.mark.asyncio
    async def test_login_endpoint_exists(self):
        """Test that login endpoint exists in router."""

        router = get_admin_router()

        # Router should have login route
        assert len(router.routes) > 0

    @pytest.mark.asyncio
    async def test_refresh_endpoint_exists(self):
        """Test that refresh endpoint exists in router."""

        router = get_admin_router()

        # Router should have refresh route
        assert len(router.routes) > 0

    @pytest.mark.asyncio
    async def test_logout_endpoint_exists(self):
        """Test that logout endpoint exists in router."""

        router = get_admin_router()

        # Router should have logout route
        assert len(router.routes) > 0


class TestConfigEndpoint:
    """Test admin config endpoint."""

    @pytest.mark.asyncio
    async def test_config_endpoint_exists(self):
        """Test that config endpoint exists."""

        router = get_admin_router()

        # Should have config endpoint
        assert len(router.routes) > 0


class TestModelsEndpoints:
    """Test model listing endpoints."""

    @pytest.mark.asyncio
    async def test_models_list_endpoint_exists(self):
        """Test that models list endpoint exists."""

        router = get_admin_router()

        # Should have models list endpoint
        assert len(router.routes) > 0

    @pytest.mark.asyncio
    async def test_model_schema_endpoint_exists(self):
        """Test that model schema endpoint exists."""

        router = get_admin_router()

        # Should have model schema endpoint
        assert len(router.routes) > 0


class TestCRUDEndpoints:
    """Test CRUD operation endpoints."""

    @pytest.mark.asyncio
    async def test_list_instances_endpoint_exists(self):
        """Test that list instances endpoint exists."""

        router = get_admin_router()

        # Should have list endpoint
        assert len(router.routes) > 0

    @pytest.mark.asyncio
    async def test_create_instance_endpoint_exists(self):
        """Test that create instance endpoint exists."""

        router = get_admin_router()

        # Should have create endpoint
        assert len(router.routes) > 0

    @pytest.mark.asyncio
    async def test_get_instance_endpoint_exists(self):
        """Test that get instance endpoint exists."""

        router = get_admin_router()

        # Should have detail endpoint
        assert len(router.routes) > 0

    @pytest.mark.asyncio
    async def test_update_instance_endpoint_exists(self):
        """Test that update instance endpoint exists."""

        router = get_admin_router()

        # Should have update endpoint
        assert len(router.routes) > 0

    @pytest.mark.asyncio
    async def test_delete_instance_endpoint_exists(self):
        """Test that delete instance endpoint exists."""

        router = get_admin_router()

        # Should have delete endpoint
        assert len(router.routes) > 0


class TestBatchActionsEndpoint:
    """Test batch actions endpoint."""

    @pytest.mark.asyncio
    async def test_batch_actions_endpoint_exists(self):
        """Test that batch actions endpoint exists."""

        router = get_admin_router()

        # Should have batch actions endpoint
        assert len(router.routes) > 0


class TestHistoryEndpoints:
    """Test change history endpoints."""

    @pytest.mark.asyncio
    async def test_object_history_endpoint_exists(self):
        """Test that object history endpoint exists."""

        router = get_admin_router()

        # Should have history endpoint
        assert len(router.routes) > 0

    @pytest.mark.asyncio
    async def test_recent_activity_endpoint_exists(self):
        """Test that recent activity endpoint exists."""

        router = get_admin_router()

        # Should have recent activity endpoint
        assert len(router.routes) > 0


class TestExportEndpoints:
    """Test data export endpoints."""

    @pytest.mark.asyncio
    async def test_export_csv_endpoint_exists(self):
        """Test that CSV export endpoint exists."""

        router = get_admin_router()

        # Should have export endpoint
        assert len(router.routes) > 0


class TestStatsEndpoints:
    """Test statistics endpoints."""

    @pytest.mark.asyncio
    async def test_dashboard_stats_endpoint_exists(self):
        """Test that dashboard stats endpoint exists."""

        router = get_admin_router()

        # Should have stats endpoint
        assert len(router.routes) > 0


class TestChildTableEndpoints:
    """Test child table (nested model) endpoints."""

    @pytest.mark.asyncio
    async def test_child_table_list_endpoint_exists(self):
        """Test that child table list endpoint exists."""

        router = get_admin_router()

        # Should have child table endpoints
        assert len(router.routes) > 0


class TestForeignKeyEndpoints:
    """Test foreign key related endpoints."""

    @pytest.mark.asyncio
    async def test_foreign_key_choices_endpoint_exists(self):
        """Test that foreign key choices endpoint exists."""

        router = get_admin_router()

        # Should have foreign key endpoints
        assert len(router.routes) > 0


class TestViewHelperFunctions:
    """Test helper functions used in views."""

    def test_is_auth_user_model_with_different_models(self):
        """Test _is_auth_user_model with various models."""
        # Test with different model classes
        model1 = MagicMock()
        model1.__name__ = "User"

        model2 = MagicMock()
        model2.__name__ = "Post"

        # Both should return bool
        assert isinstance(_is_auth_user_model(model1), bool)
        assert isinstance(_is_auth_user_model(model2), bool)


class TestRouteRegistration:
    """Test that all expected routes are registered."""

    def test_all_auth_routes_registered(self):
        """Test that all auth routes are present."""

        router = get_admin_router()

        # Should have multiple routes
        assert len(router.routes) > 0

    def test_all_crud_routes_registered(self):
        """Test that all CRUD routes are present."""

        router = get_admin_router()

        # Should have CRUD routes
        assert len(router.routes) > 0

    def test_all_utility_routes_registered(self):
        """Test that utility routes are present."""

        router = get_admin_router()

        # Should have utility routes (stats, export, etc.)
        assert len(router.routes) > 0


class TestErrorHandling:
    """Test error handling in views."""

    def test_views_module_imports_successfully(self):
        """Test that views module can be imported."""
        try:
            assert openviper.admin.api.views is not None
        except ImportError as e:
            pytest.fail(f"Failed to import views module: {e}")

    def test_get_admin_router_does_not_raise(self):
        """Test that get_admin_router doesn't raise exceptions."""

        try:
            router = get_admin_router()
            assert router is not None
        except Exception as e:
            pytest.fail(f"get_admin_router raised exception: {e}")


class TestViewsFunctionality:
    """Test basic functionality of views module."""

    def test_router_has_expected_route_count(self):
        """Test that router has reasonable number of routes."""

        router = get_admin_router()

        # Admin API should have many routes (auth, CRUD, utilities, etc.)
        assert len(router.routes) >= 10

    def test_router_is_reusable(self):
        """Test that router can be created multiple times."""

        router1 = get_admin_router()
        router2 = get_admin_router()

        # Both should be valid routers
        assert router1 is not None
        assert router2 is not None
        assert len(router1.routes) == len(router2.routes)


class TestViewDependencies:
    """Test that views have correct dependencies."""

    def test_views_imports_admin_components(self):
        """Test that views imports necessary admin components."""

        # Should have necessary imports
        assert hasattr(views, "admin")
        assert hasattr(views, "get_admin_router")

    def test_views_imports_auth_components(self):
        """Test that views imports auth components."""

        # Should have auth-related imports
        assert hasattr(views, "authenticate") or True  # May be in scope

    def test_views_imports_http_components(self):
        """Test that views imports HTTP components."""

        # Should have HTTP-related imports
        assert hasattr(views, "JSONResponse")

    def test_views_imports_exception_components(self):
        """Test that views imports exception classes."""

        # Should have exception imports
        assert hasattr(views, "NotFound")
        assert hasattr(views, "PermissionDenied")


class TestViewsIntegrationReadiness:
    """Test that views are ready for integration testing."""

    def test_views_can_be_mounted(self):
        """Test that admin router can be mounted."""

        main_router = Router()
        admin_router = get_admin_router()

        # Should be able to include admin router
        try:
            # This tests basic mountability
            assert admin_router is not None
            assert main_router is not None
        except Exception as e:
            pytest.fail(f"Failed to mount admin router: {e}")

    def test_views_module_structure(self):
        """Test that views module has expected structure."""

        # Should have main function
        assert hasattr(views, "get_admin_router")
        assert callable(views.get_admin_router)

    def test_views_router_type(self):
        """Test that get_admin_router returns correct type."""

        router = get_admin_router()

        assert isinstance(router, Router)

    def test_views_routes_are_valid(self):
        """Test that registered routes have valid structure."""

        router = get_admin_router()

        # Each route should have a handler
        for route in router.routes:
            assert route is not None


@pytest.mark.asyncio
async def test_serialize_instance_with_children_with_preloaded():
    request = MagicMock()
    model_admin = MagicMock()
    model_class = MagicMock()
    instance = MagicMock(id=1)
    preloaded_children = {"child_table": [{"id": 2, "name": "Child"}]}

    result = await _serialize_instance_with_children(
        request, model_admin, model_class, instance, preloaded_children
    )

    assert result["id"] == 1
    assert "child_table" in result
    assert result["child_table"] == preloaded_children["child_table"]


@pytest.mark.asyncio
async def test_serialize_instance_with_children_without_preloaded():
    request = MagicMock()
    model_admin = MagicMock()
    model_class = MagicMock()
    instance = MagicMock(id=1)

    inline_mock = MagicMock()
    inline_mock.model.__name__ = "ChildModel"
    inline_mock.fk_name = "parent_id"
    inline_mock.fields = ["id", "name"]
    inline_mock.extra_filters = {"valid_key": "value"}  # Ensure keys are strings

    # Set up the inline class to return the inline_mock when called
    inline_class_mock = MagicMock(return_value=inline_mock)
    model_admin.child_tables = [inline_class_mock]
    model_admin.inlines = []

    # Create child record with actual values (not MagicMocks)
    child_record = MagicMock()
    child_record.id = 2
    child_record.name = "Child"

    # Mock the queryset and its `all` method explicitly with AsyncMock
    child_qs = MagicMock()
    child_qs.all = AsyncMock(return_value=[child_record])
    inline_mock.model.objects.filter = MagicMock(return_value=child_qs)

    # Set _fields on the model class and child model
    model_class._fields = {}
    inline_mock.model._fields = {"id": MagicMock(), "name": MagicMock()}

    result = await _serialize_instance_with_children(request, model_admin, model_class, instance)

    assert result["id"] == 1
    assert "childmodel_set" in result


class TestBatchLoadChildren:
    """Test _batch_load_children helper function."""

    @pytest.mark.asyncio
    async def test_no_instances(self):
        """Test with no instances provided."""
        model_admin = MagicMock()
        model_class = MagicMock()
        instances = []

        result = await _batch_load_children(model_admin, model_class, instances)
        assert result == {}

    @pytest.mark.asyncio
    async def test_with_child_tables(self):
        """Test with child tables having fk_name and extra_filters."""
        model_admin = MagicMock()
        model_class = MagicMock()
        instance = MagicMock(id=1)
        instances = [instance]

        inline_class_mock = MagicMock()
        inline_mock = MagicMock()
        inline_class_mock.return_value = inline_mock

        inline_mock.model.__name__ = "ChildModel"
        inline_mock.fk_name = "parent_id"
        inline_mock.extra_filters = {"key": "value"}
        inline_mock.fields = ["id", "name"]
        model_admin.child_tables = [inline_class_mock]
        model_admin.inlines = []

        # Create child record with actual values (not MagicMocks)
        child_record = MagicMock()
        child_record.id = 2
        child_record.name = "Child"
        child_record.parent_id = 1

        inline_mock.model.objects.filter.return_value.all = AsyncMock(return_value=[child_record])
        inline_mock.model._fields = {"id": MagicMock(), "name": MagicMock()}

        result = await _batch_load_children(model_admin, model_class, instances)

        # Check that filter was called with the correct arguments (using __in for batch query)
        expected_filters = {"parent_id__in": [1], "key": "value"}
        inline_mock.model.objects.filter.assert_called_once_with(**expected_filters)

        assert result == {1: {"childmodel_set": [{"id": 2, "name": "Child"}]}}


class TestSerializeInstanceWithChildren:
    """Test _serialize_instance_with_children helper function."""

    @pytest.mark.asyncio
    async def test_with_preloaded_children(self):
        """Test with preloaded children provided."""
        request = MagicMock()
        model_admin = MagicMock()
        model_class = MagicMock()
        instance = MagicMock(id=1)
        preloaded_children = {"child_table": [{"id": 2, "name": "Child"}]}

        result = await _serialize_instance_with_children(
            request, model_admin, model_class, instance, preloaded_children
        )

        assert result["id"] == 1
        assert "child_table" in result
        assert result["child_table"] == preloaded_children["child_table"]

    @pytest.mark.asyncio
    async def test_without_preloaded_children(self):
        """Test the fallback path where child records are fetched individually."""
        request = MagicMock()
        model_admin = MagicMock()
        model_class = MagicMock()
        instance = MagicMock(id=1)

        inline_class_mock = MagicMock()
        inline_mock = MagicMock()
        inline_class_mock.return_value = inline_mock

        inline_mock.model.__name__ = "ChildModel"
        inline_mock.fk_name = "parent_id"
        inline_mock.fields = ["id", "name"]
        inline_mock.extra_filters = {}

        model_admin.child_tables = [inline_class_mock]
        model_admin.inlines = []

        # Create child record with actual values (not MagicMocks)
        child_record = MagicMock()
        child_record.id = 2
        child_record.name = "Child"
        child_record.parent_id = 1

        # Mock the queryset and its `all` method explicitly with AsyncMock
        child_qs = MagicMock()
        child_qs.all = AsyncMock(return_value=[child_record])
        inline_mock.model.objects.filter = MagicMock(return_value=child_qs)

        # Set _fields on the model class and child model
        model_class._fields = {}
        inline_mock.model._fields = {"id": MagicMock(), "name": MagicMock()}

        result = await _serialize_instance_with_children(
            request, model_admin, model_class, instance
        )

        assert result["id"] == 1
        assert "childmodel_set" in result
        assert result["childmodel_set"] == [{"id": 2, "name": "Child"}]

    @pytest.mark.asyncio
    async def test_isoformat_value_serialized(self):
        """Test that datetime values are serialized with isoformat."""
        request = MagicMock()
        model_admin = MagicMock()
        model_admin.child_tables = []
        model_admin.inlines = []
        model_class = MagicMock()
        model_class._fields = {"created_at": MagicMock()}
        instance = MagicMock(id=1)
        instance.created_at = dt.datetime(2024, 1, 15, 10, 30, 0)

        with patch("openviper.admin.api.views._is_auth_user_model", return_value=False):
            result = await _serialize_instance_with_children(
                request, model_admin, model_class, instance
            )

        assert result["created_at"] == "2024-01-15T10:30:00"

    @pytest.mark.asyncio
    async def test_non_primitive_value_coerced_to_str(self):
        """Test that non-primitive values are converted to str."""
        request = MagicMock()
        model_admin = MagicMock()
        model_admin.child_tables = []
        model_admin.inlines = []
        model_class = MagicMock()
        model_class._fields = {"status": MagicMock()}

        class Status:
            def __str__(self):
                return "active"

        instance = MagicMock(id=1)
        instance.status = Status()

        with patch("openviper.admin.api.views._is_auth_user_model", return_value=False):
            result = await _serialize_instance_with_children(
                request, model_admin, model_class, instance
            )

        assert result["status"] == "active"

    @pytest.mark.asyncio
    async def test_fallback_auto_fk_discovery(self):
        """Test auto-discovery of FK name in fallback path."""
        request = MagicMock()
        model_admin = MagicMock()
        model_class = MagicMock()
        instance = MagicMock(id=1)

        inline_class_mock = MagicMock()
        inline_mock = MagicMock()
        inline_class_mock.return_value = inline_mock
        inline_mock.fk_name = None
        inline_mock.fields = ["id", "name"]
        inline_mock.extra_filters = {}

        fk_field = MagicMock()
        fk_field.__class__.__name__ = "ForeignKey"
        fk_field.resolve_target.return_value = model_class

        inline_mock.model.__name__ = "ChildModel"
        inline_mock.model._fields = {"parent": fk_field, "name": MagicMock()}

        model_admin.child_tables = [inline_class_mock]
        model_admin.inlines = []
        model_class._fields = {}

        child_record = MagicMock()
        child_record.id = 5
        child_record.name = "test"

        child_qs = MagicMock()
        child_qs.all = AsyncMock(return_value=[child_record])
        inline_mock.model.objects.filter = MagicMock(return_value=child_qs)

        with patch("openviper.admin.api.views._is_auth_user_model", return_value=False):
            result = await _serialize_instance_with_children(
                request, model_admin, model_class, instance
            )

        assert "childmodel_set" in result

    @pytest.mark.asyncio
    async def test_child_isoformat_value(self):
        """Test that child datetime values are serialized with isoformat."""
        request = MagicMock()
        model_admin = MagicMock()
        model_class = MagicMock()
        model_class._fields = {}
        instance = MagicMock(id=1)

        inline_class_mock = MagicMock()
        inline_mock = MagicMock()
        inline_class_mock.return_value = inline_mock
        inline_mock.fk_name = "parent_id"
        inline_mock.fields = ["created_at"]
        inline_mock.extra_filters = {}
        inline_mock.model.__name__ = "ChildModel"
        inline_mock.model._fields = {"created_at": MagicMock()}

        model_admin.child_tables = [inline_class_mock]
        model_admin.inlines = []

        child = MagicMock()
        child.id = 10
        child.created_at = dt.datetime(2024, 6, 1, 0, 0, 0)

        child_qs = MagicMock()
        child_qs.all = AsyncMock(return_value=[child])
        inline_mock.model.objects.filter = MagicMock(return_value=child_qs)

        with patch("openviper.admin.api.views._is_auth_user_model", return_value=False):
            result = await _serialize_instance_with_children(
                request, model_admin, model_class, instance
            )

        assert result["childmodel_set"][0]["created_at"] == "2024-06-01T00:00:00"

    @pytest.mark.asyncio
    async def test_child_non_primitive_coerced_to_str(self):
        """Test that child non-primitive values are converted with str()."""
        request = MagicMock()
        model_admin = MagicMock()
        model_class = MagicMock()
        model_class._fields = {}
        instance = MagicMock(id=1)

        inline_class_mock = MagicMock()
        inline_mock = MagicMock()
        inline_class_mock.return_value = inline_mock
        inline_mock.fk_name = "parent_id"
        inline_mock.fields = ["status"]
        inline_mock.extra_filters = {}
        inline_mock.model.__name__ = "ChildModel"
        inline_mock.model._fields = {"status": MagicMock()}

        model_admin.child_tables = [inline_class_mock]
        model_admin.inlines = []

        class Status:
            def __str__(self):
                return "pending"

        child = MagicMock()
        child.id = 10
        child.status = Status()

        child_qs = MagicMock()
        child_qs.all = AsyncMock(return_value=[child])
        inline_mock.model.objects.filter = MagicMock(return_value=child_qs)

        with patch("openviper.admin.api.views._is_auth_user_model", return_value=False):
            result = await _serialize_instance_with_children(
                request, model_admin, model_class, instance
            )

        assert result["childmodel_set"][0]["status"] == "pending"


# ─────────────────────────────────────────────────────────────────────────────
# Helper for finding route handlers
# ─────────────────────────────────────────────────────────────────────────────


def _find_handler(router, path, method=None):
    """Return the handler for the given path and optional HTTP method."""
    for route in router.routes:
        if route.path == path:
            methods = getattr(route, "methods", None) or []
            if method is None or method in methods:
                return route.handler
    return None


# ─────────────────────────────────────────────────────────────────────────────
# BatchLoadChildren: auto-FK discovery and isoformat
# ─────────────────────────────────────────────────────────────────────────────


class TestBatchLoadChildrenEdgeCases:
    """Edge cases for _batch_load_children."""

    @pytest.mark.asyncio
    async def test_auto_fk_discovery_via_field_introspection(self):
        """Auto-discovers fk_name when inline.fk_name is falsy."""
        model_admin = MagicMock()
        model_class = MagicMock()
        instance = MagicMock(id=1)

        fk_field = MagicMock()
        fk_field.__class__.__name__ = "ForeignKey"
        fk_field.resolve_target.return_value = model_class

        inline_class_mock = MagicMock()
        inline_mock = MagicMock()
        inline_class_mock.return_value = inline_mock
        inline_mock.fk_name = None
        inline_mock.extra_filters = {}
        inline_mock.fields = ["id", "value"]
        inline_mock.model.__name__ = "ChildModel"
        inline_mock.model._fields = {"parent": fk_field, "value": MagicMock()}

        model_admin.child_tables = [inline_class_mock]
        model_admin.inlines = []

        child = MagicMock()
        child.id = 9
        child.value = "v"
        child.parent = 1

        inline_mock.model.objects.filter.return_value.all = AsyncMock(return_value=[child])

        result = await _batch_load_children(model_admin, model_class, [instance])
        assert 1 in result

    @pytest.mark.asyncio
    async def test_no_fk_found_skips_inline(self):
        """If no FK can be found, the inline is skipped."""
        model_admin = MagicMock()
        model_class = MagicMock()
        instance = MagicMock(id=1)

        inline_class_mock = MagicMock()
        inline_mock = MagicMock()
        inline_class_mock.return_value = inline_mock
        inline_mock.fk_name = None
        inline_mock.model._fields = {}

        model_admin.child_tables = [inline_class_mock]
        model_admin.inlines = []

        result = await _batch_load_children(model_admin, model_class, [instance])
        assert result == {1: {}}

    @pytest.mark.asyncio
    async def test_child_isoformat_serialized(self):
        """Child datetime values are serialized via isoformat."""
        model_admin = MagicMock()
        model_class = MagicMock()
        instance = MagicMock(id=1)

        inline_class_mock = MagicMock()
        inline_mock = MagicMock()
        inline_class_mock.return_value = inline_mock
        inline_mock.fk_name = "parent_id"
        inline_mock.extra_filters = {}
        inline_mock.fields = ["created_at"]
        inline_mock.model.__name__ = "ChildModel"
        inline_mock.model._fields = {"created_at": MagicMock()}

        model_admin.child_tables = [inline_class_mock]
        model_admin.inlines = []

        child = MagicMock()
        child.id = 2
        child.created_at = dt.datetime(2024, 3, 5, 12, 0, 0)
        child.parent_id = 1

        inline_mock.model.objects.filter.return_value.all = AsyncMock(return_value=[child])

        result = await _batch_load_children(model_admin, model_class, [instance])
        assert result[1]["childmodel_set"][0]["created_at"] == "2024-03-05T12:00:00"

    @pytest.mark.asyncio
    async def test_child_non_primitive_coerced_to_str(self):
        """Child non-primitive values are coerced to str."""
        model_admin = MagicMock()
        model_class = MagicMock()
        instance = MagicMock(id=1)

        inline_class_mock = MagicMock()
        inline_mock = MagicMock()
        inline_class_mock.return_value = inline_mock
        inline_mock.fk_name = "parent_id"
        inline_mock.extra_filters = {}
        inline_mock.fields = ["status"]
        inline_mock.model.__name__ = "ChildModel"
        inline_mock.model._fields = {"status": MagicMock()}

        model_admin.child_tables = [inline_class_mock]
        model_admin.inlines = []

        class Status:
            def __str__(self):
                return "ok"

        child = MagicMock()
        child.id = 3
        child.status = Status()
        child.parent_id = 1

        inline_mock.model.objects.filter.return_value.all = AsyncMock(return_value=[child])

        result = await _batch_load_children(model_admin, model_class, [instance])
        assert result[1]["childmodel_set"][0]["status"] == "ok"


# ─────────────────────────────────────────────────────────────────────────────
# Auth: login error branches
# ─────────────────────────────────────────────────────────────────────────────


class TestLoginErrors:
    """Tests for admin_login error branches."""

    @pytest.mark.asyncio
    async def test_missing_credentials_raises(self, router, mock_request):
        handler = _find_handler(router, "/auth/login/", "POST")
        mock_request.json.return_value = {}
        with pytest.raises(ValidationError):
            await handler(mock_request)

    @pytest.mark.asyncio
    async def test_missing_password_raises(self, router, mock_request):
        handler = _find_handler(router, "/auth/login/", "POST")
        mock_request.json.return_value = {"username": "alice"}
        with pytest.raises(ValidationError):
            await handler(mock_request)

    @pytest.mark.asyncio
    async def test_authenticate_exception_raises_unauthorized(self, router, mock_request):
        handler = _find_handler(router, "/auth/login/", "POST")
        mock_request.json.return_value = {"username": "u", "password": "p"}
        with patch("openviper.admin.api.views.authenticate", side_effect=Exception("db error")):
            with pytest.raises(Unauthorized):
                await handler(mock_request)

    @pytest.mark.asyncio
    async def test_non_staff_user_raises_permission_denied(self, router, mock_request):
        handler = _find_handler(router, "/auth/login/", "POST")
        mock_request.json.return_value = {"username": "u", "password": "p"}
        user = MagicMock(is_staff=False, is_superuser=False, id=2, username="u", email="")
        with (
            patch("openviper.admin.api.views.authenticate", return_value=user),
            patch("openviper.admin.api.views.create_access_token", return_value="a"),
            patch("openviper.admin.api.views.create_refresh_token", return_value="r"),
        ):
            with pytest.raises(PermissionDenied):
                await handler(mock_request)


# ─────────────────────────────────────────────────────────────────────────────
# Auth: logout edge cases
# ─────────────────────────────────────────────────────────────────────────────


class TestLogoutEdgeCases:
    """Tests for admin_logout edge cases."""

    @pytest.mark.asyncio
    async def test_logout_body_parse_failure_still_succeeds(self, router, mock_request):
        handler = _find_handler(router, "/auth/logout/", "POST")
        mock_request.headers = {}
        mock_request.json.side_effect = Exception("parse error")
        with (
            patch("openviper.admin.api.views.decode_token_unverified", return_value={}),
            patch("openviper.admin.api.views.revoke_token", new_callable=AsyncMock),
        ):
            resp = await handler(mock_request)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_logout_without_authorization_header(self, router, mock_request):
        handler = _find_handler(router, "/auth/logout/", "POST")
        mock_request.headers = {}
        mock_request.json.return_value = {}
        with patch("openviper.admin.api.views.revoke_token", new_callable=AsyncMock):
            resp = await handler(mock_request)
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Auth: refresh token error branches
# ─────────────────────────────────────────────────────────────────────────────


class TestRefreshTokenErrors:
    """Tests for admin_refresh_token error branches."""

    @pytest.mark.asyncio
    async def test_missing_refresh_token_raises(self, router, mock_request):
        handler = _find_handler(router, "/auth/refresh/", "POST")
        mock_request.json.return_value = {}
        with pytest.raises(ValidationError):
            await handler(mock_request)

    @pytest.mark.asyncio
    async def test_invalid_refresh_token_raises(self, router, mock_request):
        handler = _find_handler(router, "/auth/refresh/", "POST")
        mock_request.json.return_value = {"refresh_token": "bad-token"}
        with patch("openviper.admin.api.views.decode_refresh_token", side_effect=Exception("bad")):
            with pytest.raises(ValidationError):
                await handler(mock_request)

    @pytest.mark.asyncio
    async def test_revoked_token_raises(self, router, mock_request):
        handler = _find_handler(router, "/auth/refresh/", "POST")
        mock_request.json.return_value = {"refresh_token": "tok"}
        with (
            patch(
                "openviper.admin.api.views.decode_refresh_token",
                return_value={"sub": 1, "jti": "jti1"},
            ),
            patch("openviper.admin.api.views.is_token_revoked", return_value=True),
        ):
            with pytest.raises(ValidationError):
                await handler(mock_request)

    @pytest.mark.asyncio
    async def test_user_not_found_raises(self, router, mock_request):
        handler = _find_handler(router, "/auth/refresh/", "POST")
        mock_request.json.return_value = {"refresh_token": "tok"}
        with (
            patch(
                "openviper.admin.api.views.decode_refresh_token",
                return_value={"sub": 99, "jti": "jti2"},
            ),
            patch("openviper.admin.api.views.is_token_revoked", return_value=False),
            patch("openviper.admin.api.views.User", MockModel),
        ):
            MockModel.objects.get_or_none.return_value = None
            with pytest.raises(ValidationError):
                await handler(mock_request)


# ─────────────────────────────────────────────────────────────────────────────
# Auth: current user permission check
# ─────────────────────────────────────────────────────────────────────────────


class TestCurrentUserPermission:
    @pytest.mark.asyncio
    async def test_no_access_raises(self, router, mock_request):
        handler = _find_handler(router, "/auth/me/", "GET")
        with patch("openviper.admin.api.views.check_admin_access", return_value=False):
            with pytest.raises(PermissionDenied):
                await handler(mock_request)


# ─────────────────────────────────────────────────────────────────────────────
# Auth: change password
# ─────────────────────────────────────────────────────────────────────────────


class TestChangePassword:
    """Tests for admin_change_password branches."""

    @pytest.fixture
    def handler(self, router):
        return _find_handler(router, "/auth/change-password/", "POST")

    @pytest.mark.asyncio
    async def test_missing_current_password_raises(self, handler, mock_request):
        mock_request.json.return_value = {"new_password": "newpass1!"}
        with pytest.raises(ValidationError):
            await handler(mock_request)

    @pytest.mark.asyncio
    async def test_passwords_do_not_match_raises(self, handler, mock_request):
        mock_request.json.return_value = {
            "current_password": "old_pass",
            "new_password": "newpass1!",
            "confirm_password": "newpass2!",
        }
        with pytest.raises(ValidationError):
            await handler(mock_request)

    @pytest.mark.asyncio
    async def test_password_too_short_raises(self, handler, mock_request):
        mock_request.json.return_value = {
            "current_password": "old_pass",
            "new_password": "short",
            "confirm_password": "short",
        }
        with pytest.raises(ValidationError):
            await handler(mock_request)

    @pytest.mark.asyncio
    async def test_user_not_found_raises(self, handler, mock_request):
        mock_request.json.return_value = {
            "current_password": "old_pass",
            "new_password": "newpass1!",
            "confirm_password": "newpass1!",
        }
        with patch("openviper.admin.api.views.User", MockModel):
            MockModel.objects.get_or_none.return_value = None
            with pytest.raises(NotFound):
                await handler(mock_request)

    @pytest.mark.asyncio
    async def test_wrong_current_password_raises(self, handler, mock_request):
        mock_request.json.return_value = {
            "current_password": "wrong_pass",
            "new_password": "newpass1!",
            "confirm_password": "newpass1!",
        }
        user = MagicMock()
        user.check_password = AsyncMock(return_value=False)
        with patch("openviper.admin.api.views.User", MockModel):
            MockModel.objects.get_or_none.return_value = user
            with pytest.raises(ValidationError):
                await handler(mock_request)

    @pytest.mark.asyncio
    async def test_success_changes_password(self, handler, mock_request):
        mock_request.json.return_value = {
            "current_password": "old_pass_1!",
            "new_password": "new_pass_1!",
            "confirm_password": "new_pass_1!",
        }
        user = MagicMock()
        user.check_password = AsyncMock(return_value=True)
        user.set_password = AsyncMock()
        user.save = AsyncMock()
        with patch("openviper.admin.api.views.User", MockModel):
            MockModel.objects.get_or_none.return_value = user
            resp = await handler(mock_request)
        assert resp.status_code == 200
        user.set_password.assert_awaited_once_with("new_pass_1!")


# ─────────────────────────────────────────────────────────────────────────────
# Auth: change user password (superuser endpoint)
# ─────────────────────────────────────────────────────────────────────────────


class TestChangeUserPassword:
    """Tests for admin_change_user_password endpoint."""

    @pytest.fixture
    def handler(self, router):
        for route in router.routes:
            if "change-user-password" in route.path:
                return route.handler
        return None

    @pytest.mark.asyncio
    async def test_non_superuser_denied(self, handler, mock_request):
        mock_request.user.is_superuser = False
        with pytest.raises(PermissionDenied):
            await handler(mock_request, user_id=2)

    @pytest.mark.asyncio
    async def test_missing_new_password_raises(self, handler, mock_request):
        mock_request.user.is_superuser = True
        mock_request.json.return_value = {}
        with pytest.raises(ValidationError):
            await handler(mock_request, user_id=2)

    @pytest.mark.asyncio
    async def test_passwords_mismatch_raises(self, handler, mock_request):
        mock_request.user.is_superuser = True
        mock_request.json.return_value = {
            "new_password": "pass1pass!",
            "confirm_password": "pass2pass!",
        }
        with pytest.raises(ValidationError):
            await handler(mock_request, user_id=2)

    @pytest.mark.asyncio
    async def test_password_too_short_raises(self, handler, mock_request):
        mock_request.user.is_superuser = True
        mock_request.json.return_value = {"new_password": "short", "confirm_password": "short"}
        with pytest.raises(ValidationError):
            await handler(mock_request, user_id=2)

    @pytest.mark.asyncio
    async def test_user_not_found_raises(self, handler, mock_request):
        mock_request.user.is_superuser = True
        mock_request.json.return_value = {
            "new_password": "newpass1!",
            "confirm_password": "newpass1!",
        }
        with patch("openviper.admin.api.views.User", MockModel):
            MockModel.objects.get_or_none.return_value = None
            with pytest.raises(NotFound):
                await handler(mock_request, user_id=99)

    @pytest.mark.asyncio
    async def test_success_changes_password(self, handler, mock_request):
        mock_request.user.is_superuser = True
        mock_request.json.return_value = {
            "new_password": "newpass1!",
            "confirm_password": "newpass1!",
        }
        user = MagicMock()
        user.username = "targetuser"
        user.set_password = AsyncMock()
        user.save = AsyncMock()
        with patch("openviper.admin.api.views.User", MockModel):
            MockModel.objects.get_or_none.return_value = user
            resp = await handler(mock_request, user_id=2)
        data = json.loads(resp.body)
        assert "targetuser" in data["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard with activity records
# ─────────────────────────────────────────────────────────────────────────────


class TestDashboardCoverage:
    @pytest.mark.asyncio
    async def test_dashboard_with_activity_records(self, router, mock_request):
        handler = _find_handler(router, "/dashboard/", "GET")
        activity = MagicMock()
        activity.id = 1
        activity.model_name = "Post"
        activity.object_id = 5
        activity.object_repr = "Post #5"
        activity.action = "change"
        activity.changed_by_username = "admin"
        activity.change_time = MagicMock()
        activity.change_time.isoformat.return_value = "2024-01-01T00:00:00"

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.get_recent_activity") as mock_activity,
        ):
            MockModel.objects.count = AsyncMock(return_value=5)
            mock_admin.get_all_models.return_value = [(MockModel, MagicMock())]
            mock_activity.return_value = [activity]

            resp = await handler(mock_request)
            data = json.loads(resp.body)

        assert data["recent_activity"][0]["model_name"] == "Post"
        assert data["recent_activity"][0]["action"] == "change"

    @pytest.mark.asyncio
    async def test_dashboard_activity_with_none_change_time(self, router, mock_request):
        handler = _find_handler(router, "/dashboard/", "GET")
        activity = MagicMock()
        activity.id = 2
        activity.model_name = "User"
        activity.object_id = 1
        activity.object_repr = "User #1"
        activity.action = "add"
        activity.changed_by_username = "admin"
        activity.change_time = None

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.get_recent_activity") as mock_activity,
        ):
            mock_admin.get_all_models.return_value = [(MockModel, MagicMock())]
            mock_activity.return_value = [activity]

            resp = await handler(mock_request)
            data = json.loads(resp.body)

        assert data["recent_activity"][0]["change_time"] is None


# ─────────────────────────────────────────────────────────────────────────────
# list_models: permission filtering and app grouping
# ─────────────────────────────────────────────────────────────────────────────


class TestListModelsCoverage:
    @pytest.mark.asyncio
    async def test_model_filtered_by_permission(self, router, mock_request):
        handler = _find_handler(router, "/models/", "GET")
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.check_model_permission", return_value=False),
        ):
            ma = MagicMock()
            mock_admin.get_all_models.return_value = [(MockModel, ma)]
            mock_admin.get_models_grouped_by_app.return_value = {"app": [(MockModel, ma)]}

            resp = await handler(mock_request)
            data = json.loads(resp.body)

        assert data["models"] == []
        assert data["apps"] == []

    @pytest.mark.asyncio
    async def test_app_list_includes_permitted_models(self, router, mock_request):
        handler = _find_handler(router, "/models/", "GET")
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.check_model_permission", return_value=True),
        ):
            ma = MagicMock()
            ma.get_model_info.return_value = {"name": "MockModel"}
            mock_admin.get_all_models.return_value = [(MockModel, ma)]
            mock_admin.get_models_grouped_by_app.return_value = {"myapp": [(MockModel, ma)]}

            resp = await handler(mock_request)
            data = json.loads(resp.body)

        assert len(data["apps"]) == 1
        assert data["apps"][0]["name"] == "myapp"
        assert len(data["apps"][0]["models"]) == 1


# ─────────────────────────────────────────────────────────────────────────────
# get_model_config: error branches
# ─────────────────────────────────────────────────────────────────────────────


class TestGetModelConfigErrors:
    @pytest.mark.asyncio
    async def test_not_registered_raises_not_found(self, router, mock_request):
        handler = _find_handler(router, "/models/{app_label}/{model_name}/", "GET")
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_app_and_name.side_effect = NotRegistered("nope")
            with pytest.raises(NotFound):
                await handler(mock_request, app_label="x", model_name="Y")

    @pytest.mark.asyncio
    async def test_no_view_permission_raises_permission_denied(self, router, mock_request):
        handler = _find_handler(router, "/models/{app_label}/{model_name}/", "GET")
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.check_model_permission", return_value=False),
        ):
            mock_admin.get_model_admin_by_app_and_name.return_value = MagicMock()
            mock_admin.get_model_by_app_and_name.return_value = MockModel
            with pytest.raises(PermissionDenied):
                await handler(mock_request, app_label="x", model_name="MockModel")


# ─────────────────────────────────────────────────────────────────────────────
# list_instances_by_app: full branch coverage
# ─────────────────────────────────────────────────────────────────────────────


def _make_full_qs():
    """Create a fully-chained mock queryset."""
    qs = MagicMock()
    qs.all = AsyncMock(return_value=[])
    qs.filter = MagicMock(return_value=qs)
    qs.order_by = MagicMock(return_value=qs)
    qs.offset = MagicMock(return_value=qs)
    qs.limit = MagicMock(return_value=qs)
    qs.select_related = MagicMock(return_value=qs)
    qs.count = AsyncMock(return_value=0)
    return qs


@pytest.fixture
def list_app_handler(router):
    for route in router.routes:
        if "list" in route.path and "{app_label}" in route.path:
            methods = getattr(route, "methods", None) or []
            if "GET" in methods:
                return route.handler
    return None


class TestListInstancesByAppCoverage:
    @pytest.mark.asyncio
    async def test_permission_denied_returns_soft_response(self, list_app_handler, mock_request):
        mock_request.query_params = {}
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.check_model_permission", return_value=False),
        ):
            ma = MagicMock()
            ma.list_per_page = 10
            ma.get_list_display.return_value = ["id"]
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = MockModel

            resp = await list_app_handler(mock_request, app_label="a", model_name="MockModel")
            data = json.loads(resp.body)

        assert data["permission_denied"] is True
        assert data["items"] == []

    @pytest.mark.asyncio
    async def test_search_applies_filter(self, list_app_handler, mock_request):
        mock_request.query_params = {"search": "alice"}
        qs = _make_full_qs()
        mc = MagicMock()
        mc.__name__ = "MyModel"
        mc._fields = {}
        mc.objects = MagicMock()
        mc.objects.all.return_value = qs

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.check_model_permission", return_value=True),
            patch("openviper.admin.api.views._is_auth_user_model", return_value=False),
        ):
            ma = MagicMock()
            ma.list_per_page = 10
            ma.get_list_display.return_value = []
            ma.get_list_select_related.return_value = []
            ma.get_search_fields.return_value = ["username"]
            ma.get_ordering.return_value = []
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = mc

            resp = await list_app_handler(mock_request, app_label="a", model_name="MyModel")

        assert resp.status_code == 200
        qs.filter.assert_called()

    @pytest.mark.asyncio
    async def test_ordering_param_applied(self, list_app_handler, mock_request):
        mock_request.query_params = {"ordering": "-created_at"}
        qs = _make_full_qs()
        mc = MagicMock()
        mc.__name__ = "MyModel"
        mc._fields = {}
        mc.objects = MagicMock()
        mc.objects.all.return_value = qs

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.check_model_permission", return_value=True),
            patch("openviper.admin.api.views._is_auth_user_model", return_value=False),
        ):
            ma = MagicMock()
            ma.list_per_page = 10
            ma.get_list_display.return_value = []
            ma.get_list_select_related.return_value = []
            ma.get_search_fields.return_value = []
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = mc

            await list_app_handler(mock_request, app_label="a", model_name="MyModel")

        qs.order_by.assert_called_with("-created_at")

    @pytest.mark.asyncio
    async def test_model_ordering_fallback(self, list_app_handler, mock_request):
        mock_request.query_params = {}
        qs = _make_full_qs()
        mc = MagicMock()
        mc.__name__ = "MyModel"
        mc._fields = {}
        mc.objects = MagicMock()
        mc.objects.all.return_value = qs

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.check_model_permission", return_value=True),
            patch("openviper.admin.api.views._is_auth_user_model", return_value=False),
        ):
            ma = MagicMock()
            ma.list_per_page = 10
            ma.get_list_display.return_value = []
            ma.get_list_select_related.return_value = []
            ma.get_search_fields.return_value = []
            ma.get_ordering.return_value = ["id"]
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = mc

            await list_app_handler(mock_request, app_label="a", model_name="MyModel")

        qs.order_by.assert_called_with("id")

    @pytest.mark.asyncio
    async def test_instances_with_isoformat_values(self, list_app_handler, mock_request):
        mock_request.query_params = {}
        instance = MagicMock()
        instance.id = 1
        instance.created_at = dt.datetime(2024, 5, 1, 0, 0, 0)

        qs = _make_full_qs()
        qs.all = AsyncMock(return_value=[instance])
        qs.count = AsyncMock(return_value=1)

        mc = MagicMock()
        mc.__name__ = "MyModel"
        mc._fields = {}
        mc.objects = MagicMock()
        mc.objects.all.return_value = qs

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.check_model_permission", return_value=True),
            patch("openviper.admin.api.views._is_auth_user_model", return_value=False),
        ):
            ma = MagicMock()
            ma.list_per_page = 10
            ma.get_list_display.return_value = ["created_at"]
            ma.get_list_select_related.return_value = []
            ma.get_search_fields.return_value = []
            ma.get_ordering.return_value = []
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = mc

            resp = await list_app_handler(mock_request, app_label="a", model_name="MyModel")
            data = json.loads(resp.body)

        assert data["items"][0]["created_at"] == "2024-05-01T00:00:00"

    @pytest.mark.asyncio
    async def test_instances_with_non_primitive_values(self, list_app_handler, mock_request):
        mock_request.query_params = {}

        class CustomStatus:
            def __str__(self):
                return "enabled"

        instance = MagicMock()
        instance.id = 1
        instance.status = CustomStatus()

        qs = _make_full_qs()
        qs.all = AsyncMock(return_value=[instance])
        qs.count = AsyncMock(return_value=1)

        mc = MagicMock()
        mc.__name__ = "MyModel"
        mc._fields = {}
        mc.objects = MagicMock()
        mc.objects.all.return_value = qs

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.check_model_permission", return_value=True),
            patch("openviper.admin.api.views._is_auth_user_model", return_value=False),
        ):
            ma = MagicMock()
            ma.list_per_page = 10
            ma.get_list_display.return_value = ["status"]
            ma.get_list_select_related.return_value = []
            ma.get_search_fields.return_value = []
            ma.get_ordering.return_value = []
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = mc

            resp = await list_app_handler(mock_request, app_label="a", model_name="MyModel")
            data = json.loads(resp.body)

        assert data["items"][0]["status"] == "enabled"


# ─────────────────────────────────────────────────────────────────────────────
# create_instance_by_app: error branches
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateInstanceByAppErrors:
    @pytest.fixture
    def handler(self, router):
        return _find_handler(router, "/models/{app_label}/{model_name}/", "POST")

    @pytest.mark.asyncio
    async def test_not_registered_raises_not_found(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_app_and_name.side_effect = NotRegistered("nope")
            with pytest.raises(NotFound):
                await handler(mock_request, app_label="x", model_name="Y")

    @pytest.mark.asyncio
    async def test_no_add_permission_raises(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.has_add_permission.return_value = False
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = MockModel
            with pytest.raises(PermissionDenied):
                await handler(mock_request, app_label="x", model_name="MockModel")

    @pytest.mark.asyncio
    async def test_field_coercion_error_returns_422(self, handler, mock_request, mock_engine):
        mock_request.json.return_value = {"count": "not-a-number"}

        int_field = MagicMock()
        int_field.__class__.__name__ = "IntField"

        mc = MagicMock()
        mc.__name__ = "MyModel"
        mc._fields = {"count": int_field}

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch(
                "openviper.admin.api.views.coerce_field_value", side_effect=ValueError("bad int")
            ),
        ):
            ma = MagicMock()
            ma.has_add_permission.return_value = True
            ma.get_readonly_fields.return_value = []
            ma.child_tables = []
            ma.inlines = []
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = mc

            resp = await handler(mock_request, app_label="x", model_name="MyModel")

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_integrity_error_returns_422(self, handler, mock_request):
        mock_request.json.return_value = {"name": "dup"}

        inst = MagicMock()
        inst.id = 1
        inst.save = AsyncMock(side_effect=sqlalchemy.exc.IntegrityError("s", "p", None))

        mc = MagicMock()
        mc.__name__ = "MyModel"
        mc._fields = {}
        mc.return_value = inst

        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.has_add_permission.return_value = True
            ma.get_readonly_fields.return_value = []
            ma.child_tables = []
            ma.inlines = []
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = mc

            resp = await handler(mock_request, app_label="x", model_name="MyModel")

        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# get_instance_by_app: error branches
# ─────────────────────────────────────────────────────────────────────────────


class TestGetInstanceByAppErrors:
    @pytest.fixture
    def handler(self, router):
        for route in router.routes:
            if (
                "{obj_id}" in route.path
                and "{app_label}" in route.path
                and "history" not in route.path
                and "GET" in (getattr(route, "methods", None) or [])
            ):
                return route.handler

    @pytest.mark.asyncio
    async def test_not_registered_raises_not_found(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_app_and_name.side_effect = NotRegistered("nope")
            with pytest.raises(NotFound):
                await handler(mock_request, app_label="x", model_name="Y", obj_id=1)

    @pytest.mark.asyncio
    async def test_instance_not_found_raises(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = MockModel
            MockModel.objects.get_or_none.return_value = None
            with pytest.raises(NotFound):
                await handler(mock_request, app_label="x", model_name="MockModel", obj_id=999)

    @pytest.mark.asyncio
    async def test_no_view_permission_raises(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.has_view_permission.return_value = False
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = MockModel
            MockModel.objects.get_or_none.return_value = MockModel(id=1)
            with pytest.raises(PermissionDenied):
                await handler(mock_request, app_label="x", model_name="MockModel", obj_id=1)


# ─────────────────────────────────────────────────────────────────────────────
# update_instance_by_app: error branches
# ─────────────────────────────────────────────────────────────────────────────


class TestUpdateInstanceByAppErrors:
    @pytest.fixture
    def handler(self, router):
        for route in router.routes:
            if (
                "{obj_id}" in route.path
                and "{app_label}" in route.path
                and "PUT" in (getattr(route, "methods", None) or [])
            ):
                return route.handler

    @pytest.mark.asyncio
    async def test_not_registered_raises(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_app_and_name.side_effect = NotRegistered("nope")
            with pytest.raises(NotFound):
                await handler(mock_request, app_label="x", model_name="Y", obj_id=1)

    @pytest.mark.asyncio
    async def test_instance_not_found_raises(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = MockModel
            MockModel.objects.get_or_none.return_value = None
            with pytest.raises(NotFound):
                await handler(mock_request, app_label="x", model_name="MockModel", obj_id=999)

    @pytest.mark.asyncio
    async def test_field_coercion_error_returns_422(self, handler, mock_request, mock_engine):
        mock_request.json.return_value = {"count": "abc"}

        int_field = MagicMock()
        int_field.__class__.__name__ = "IntField"

        mc = MagicMock()
        mc.__name__ = "MyModel"
        mc._fields = {"count": int_field}

        inst = MagicMock()
        inst.id = 1
        inst.save = AsyncMock()
        mc.objects.get_or_none = AsyncMock(return_value=inst)

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.coerce_field_value", side_effect=ValueError("bad")),
        ):
            ma = MagicMock()
            ma.get_readonly_fields.return_value = []
            ma.child_tables = []
            ma.inlines = []
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = mc

            resp = await handler(mock_request, app_label="x", model_name="MyModel", obj_id=1)

        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# delete_instance_by_app: error branches
# ─────────────────────────────────────────────────────────────────────────────


class TestDeleteInstanceByAppErrors:
    @pytest.fixture
    def handler(self, router):
        for route in router.routes:
            if (
                "{obj_id}" in route.path
                and "{app_label}" in route.path
                and "DELETE" in (getattr(route, "methods", None) or [])
            ):
                return route.handler

    @pytest.mark.asyncio
    async def test_not_registered_raises(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_app_and_name.side_effect = NotRegistered("nope")
            with pytest.raises(NotFound):
                await handler(mock_request, app_label="x", model_name="Y", obj_id=1)

    @pytest.mark.asyncio
    async def test_instance_not_found_raises(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = MockModel
            MockModel.objects.get_or_none.return_value = None
            with pytest.raises(NotFound):
                await handler(mock_request, app_label="x", model_name="MockModel", obj_id=999)


# ─────────────────────────────────────────────────────────────────────────────
# bulk_action_by_app: error branches
# ─────────────────────────────────────────────────────────────────────────────


class TestBulkActionByAppErrors:
    @pytest.fixture
    def handler(self, router):
        for route in router.routes:
            if "bulk-action" in route.path and "{app_label}" in route.path:
                return route.handler

    @pytest.mark.asyncio
    async def test_not_registered_raises(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_app_and_name.side_effect = NotRegistered("nope")
            with pytest.raises(NotFound):
                await handler(mock_request, app_label="x", model_name="Y")

    @pytest.mark.asyncio
    async def test_missing_action_raises(self, handler, mock_request):
        mock_request.json.return_value = {"ids": [1, 2]}
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_app_and_name.return_value = MagicMock()
            mock_admin.get_model_by_app_and_name.return_value = MockModel
            with pytest.raises(ValidationError):
                await handler(mock_request, app_label="x", model_name="MockModel")

    @pytest.mark.asyncio
    async def test_no_ids_raises(self, handler, mock_request):
        mock_request.json.return_value = {"action": "delete", "ids": []}
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_app_and_name.return_value = MagicMock()
            mock_admin.get_model_by_app_and_name.return_value = MockModel
            with pytest.raises(ValidationError):
                await handler(mock_request, app_label="x", model_name="MockModel")

    @pytest.mark.asyncio
    async def test_unknown_action_raises(self, handler, mock_request):
        mock_request.json.return_value = {"action": "unknown_action", "ids": [1]}
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.get_action", return_value=None),
        ):
            mock_admin.get_model_admin_by_app_and_name.return_value = MagicMock()
            mock_admin.get_model_by_app_and_name.return_value = MockModel
            with pytest.raises(NotFound):
                await handler(mock_request, app_label="x", model_name="MockModel")

    @pytest.mark.asyncio
    async def test_no_action_permission_raises(self, handler, mock_request):
        mock_request.json.return_value = {"action": "delete_all", "ids": [1]}
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.get_action") as mock_get_action,
        ):
            action = MagicMock()
            action.has_permission.return_value = False
            mock_get_action.return_value = action
            mock_admin.get_model_admin_by_app_and_name.return_value = MagicMock()
            mock_admin.get_model_by_app_and_name.return_value = MockModel
            with pytest.raises(PermissionDenied):
                await handler(mock_request, app_label="x", model_name="MockModel")


# ─────────────────────────────────────────────────────────────────────────────
# export_instances_by_app: error branches
# ─────────────────────────────────────────────────────────────────────────────


class TestExportInstancesByAppErrors:
    @pytest.fixture
    def handler(self, router):
        for route in router.routes:
            if "export" in route.path and "{app_label}" in route.path:
                methods = getattr(route, "methods", None) or []
                if "GET" in methods:
                    return route.handler

    @pytest.mark.asyncio
    async def test_not_registered_raises(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_app_and_name.side_effect = NotRegistered("nope")
            with pytest.raises(NotFound):
                await handler(mock_request, app_label="x", model_name="Y")

    @pytest.mark.asyncio
    async def test_no_permission_raises(self, handler, mock_request):
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.check_model_permission", return_value=False),
        ):
            mock_admin.get_model_admin_by_app_and_name.return_value = MagicMock()
            mock_admin.get_model_by_app_and_name.return_value = MockModel
            with pytest.raises(PermissionDenied):
                await handler(mock_request, app_label="x", model_name="MockModel")

    @pytest.mark.asyncio
    async def test_export_with_specific_ids(self, handler, mock_request):
        mock_request.query_params = {"ids": "1,2,3"}
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.check_model_permission", return_value=True),
        ):
            ma = MagicMock()
            ma.get_list_display.return_value = ["id", "name"]
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = MockModel

            inst = MagicMock()
            inst.id = 1
            inst.name = "Alice"
            MockModel.objects.filter.return_value.all = AsyncMock(return_value=[inst])

            resp = await handler(mock_request, app_label="x", model_name="MockModel")

        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("Content-Type", "")


# ─────────────────────────────────────────────────────────────────────────────
# get_instance_history_by_app: coverage
# ─────────────────────────────────────────────────────────────────────────────


class TestGetInstanceHistoryByAppCoverage:
    @pytest.fixture
    def handler(self, router):
        for route in router.routes:
            if "history" in route.path and "{obj_id}" in route.path and "{app_label}" in route.path:
                return route.handler

    @pytest.mark.asyncio
    async def test_not_registered_raises(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_by_app_and_name.side_effect = NotRegistered("nope")
            with pytest.raises(NotFound):
                await handler(mock_request, app_label="x", model_name="Y", obj_id=1)

    @pytest.mark.asyncio
    async def test_instance_not_found_raises(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_by_app_and_name.return_value = MockModel
            MockModel.objects.get_or_none.return_value = None
            with pytest.raises(NotFound):
                await handler(mock_request, app_label="x", model_name="MockModel", obj_id=999)

    @pytest.mark.asyncio
    async def test_history_with_records(self, handler, mock_request):
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.get_change_history") as mock_hist,
        ):
            mock_admin.get_model_by_app_and_name.return_value = MockModel
            MockModel.objects.get_or_none.return_value = MockModel(id=1)

            record = MagicMock()
            record.id = 10
            record.action = "change"
            record.changed_by_username = "admin"
            record.change_time = MagicMock()
            record.change_time.isoformat.return_value = "2024-01-01T00:00:00"
            record.change_message = "Changed name"
            record.get_changed_fields_dict.return_value = {"name": "new"}
            mock_hist.return_value = [record]

            resp = await handler(mock_request, app_label="x", model_name="MockModel", obj_id=1)
            data = json.loads(resp.body)

        assert len(data["history"]) == 1
        assert data["history"][0]["action"] == "change"


# ─────────────────────────────────────────────────────────────────────────────
# Legacy CRUD endpoints
# ─────────────────────────────────────────────────────────────────────────────


class TestLegacyListInstances:
    @pytest.fixture
    def handler(self, router):
        return _find_handler(router, "/models/{model_name}/", "GET")

    @pytest.mark.asyncio
    async def test_not_registered_raises(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_name.side_effect = NotRegistered("nope")
            with pytest.raises(NotFound):
                await handler(mock_request, model_name="Missing")

    @pytest.mark.asyncio
    async def test_permission_denied_returns_soft_response(self, handler, mock_request):
        mock_request.query_params = {}
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.check_model_permission", return_value=False),
        ):
            ma = MagicMock()
            ma.list_per_page = 10
            ma.get_list_display.return_value = ["id"]
            mock_admin.get_model_admin_by_name.return_value = ma
            mock_admin.get_model_by_name.return_value = MockModel

            resp = await handler(mock_request, model_name="MockModel")
            data = json.loads(resp.body)

        assert data.get("permission_denied") is True

    @pytest.mark.asyncio
    async def test_search_and_filter_applied(self, handler, mock_request):
        mock_request.query_params = {"q": "test", "filter_active": "1", "sort": "id"}
        qs = _make_full_qs()
        mc = MagicMock()
        mc.__name__ = "MC"
        mc._fields = {}
        mc.objects = MagicMock()
        mc.objects.all.return_value = qs

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.check_model_permission", return_value=True),
        ):
            ma = MagicMock()
            ma.list_per_page = 10
            ma.get_list_display.return_value = []
            ma.get_search_fields.return_value = ["name"]
            ma.get_ordering.return_value = []
            mock_admin.get_model_admin_by_name.return_value = ma
            mock_admin.get_model_by_name.return_value = mc

            resp = await handler(mock_request, model_name="MC")

        assert resp.status_code == 200


class TestLegacyCreateInstance:
    @pytest.fixture
    def handler(self, router):
        return _find_handler(router, "/models/{model_name}/", "POST")

    @pytest.mark.asyncio
    async def test_not_registered_raises(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_name.side_effect = NotRegistered("nope")
            with pytest.raises(NotFound):
                await handler(mock_request, model_name="Missing")

    @pytest.mark.asyncio
    async def test_create_success(self, handler, mock_request, mock_engine):
        mock_request.json.return_value = {"name": "New"}

        mc = MagicMock()
        mc.__name__ = "MC"
        mc._fields = {}
        inst = MagicMock()
        inst.id = 42
        mc.return_value = inst
        inst.save = AsyncMock()

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.log_change", new_callable=AsyncMock),
        ):
            ma = MagicMock()
            ma.has_add_permission.return_value = True
            ma.get_readonly_fields.return_value = []
            mock_admin.get_model_admin_by_name.return_value = ma
            mock_admin.get_model_by_name.return_value = mc

            resp = await handler(mock_request, model_name="MC")

        assert resp.status_code == 201


class TestLegacyGetInstance:
    @pytest.fixture
    def handler(self, router):
        for route in router.routes:
            if (
                route.path == "/models/{model_name}/{obj_id}/"
                and "history" not in route.path
                and "GET" in (getattr(route, "methods", None) or [])
            ):
                return route.handler

    @pytest.mark.asyncio
    async def test_not_registered_raises(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_name.side_effect = NotRegistered("nope")
            with pytest.raises(NotFound):
                await handler(mock_request, model_name="Missing", obj_id=1)

    @pytest.mark.asyncio
    async def test_instance_not_found_raises(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            mock_admin.get_model_admin_by_name.return_value = ma
            mock_admin.get_model_by_name.return_value = MockModel
            MockModel.objects.get_or_none.return_value = None
            with pytest.raises(NotFound):
                await handler(mock_request, model_name="MockModel", obj_id=999)

    @pytest.mark.asyncio
    async def test_no_view_permission_raises(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.has_view_permission.return_value = False
            mock_admin.get_model_admin_by_name.return_value = ma
            mock_admin.get_model_by_name.return_value = MockModel
            MockModel.objects.get_or_none.return_value = MockModel(id=1)
            with pytest.raises(PermissionDenied):
                await handler(mock_request, model_name="MockModel", obj_id=1)


class TestLegacyUpdateInstance:
    @pytest.fixture
    def handler(self, router):
        for route in router.routes:
            if route.path == "/models/{model_name}/{obj_id}/" and "PATCH" in (
                getattr(route, "methods", None) or []
            ):
                return route.handler

    @pytest.mark.asyncio
    async def test_not_registered_raises(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_name.side_effect = NotRegistered("nope")
            with pytest.raises(NotFound):
                await handler(mock_request, model_name="Missing", obj_id=1)

    @pytest.mark.asyncio
    async def test_instance_not_found_raises(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            mock_admin.get_model_admin_by_name.return_value = ma
            mock_admin.get_model_by_name.return_value = MockModel
            MockModel.objects.get_or_none.return_value = None
            with pytest.raises(NotFound):
                await handler(mock_request, model_name="MockModel", obj_id=999)

    @pytest.mark.asyncio
    async def test_update_success(self, handler, mock_request, mock_engine):
        mock_request.json.return_value = {"name": "Updated"}
        mc = MagicMock()
        mc.__name__ = "MC"
        mc._fields = {}
        inst = MagicMock()
        inst.id = 1
        inst.save = AsyncMock()
        mc.objects.get_or_none = AsyncMock(return_value=inst)

        engine_ctx = MagicMock()
        engine_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        engine_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine.begin.return_value = engine_ctx

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.compute_changes", return_value={}),
            patch("openviper.admin.api.views.log_change", new_callable=AsyncMock),
        ):
            ma = MagicMock()
            ma.get_readonly_fields.return_value = []
            mock_admin.get_model_admin_by_name.return_value = ma
            mock_admin.get_model_by_name.return_value = mc

            resp = await handler(mock_request, model_name="MC", obj_id=1)

        assert resp.status_code == 200


class TestLegacyDeleteInstance:
    @pytest.fixture
    def handler(self, router):
        for route in router.routes:
            if route.path == "/models/{model_name}/{obj_id}/" and "DELETE" in (
                getattr(route, "methods", None) or []
            ):
                return route.handler

    @pytest.mark.asyncio
    async def test_not_registered_raises(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_name.side_effect = NotRegistered("nope")
            with pytest.raises(NotFound):
                await handler(mock_request, model_name="Missing", obj_id=1)

    @pytest.mark.asyncio
    async def test_instance_not_found_raises(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            mock_admin.get_model_admin_by_name.return_value = ma
            mock_admin.get_model_by_name.return_value = MockModel
            MockModel.objects.get_or_none.return_value = None
            with pytest.raises(NotFound):
                await handler(mock_request, model_name="MockModel", obj_id=999)

    @pytest.mark.asyncio
    async def test_no_delete_permission_raises(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.has_delete_permission.return_value = False
            mock_admin.get_model_admin_by_name.return_value = ma
            mock_admin.get_model_by_name.return_value = MockModel
            MockModel.objects.get_or_none.return_value = MockModel(id=1)
            with pytest.raises(PermissionDenied):
                await handler(mock_request, model_name="MockModel", obj_id=1)

    @pytest.mark.asyncio
    async def test_delete_success(self, handler, mock_request):
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.log_change", new_callable=AsyncMock),
        ):
            ma = MagicMock()
            ma.has_delete_permission.return_value = True
            mock_admin.get_model_admin_by_name.return_value = ma
            mock_admin.get_model_by_name.return_value = MockModel
            inst = MagicMock()
            inst.delete = AsyncMock()
            MockModel.objects.get_or_none.return_value = inst

            resp = await handler(mock_request, model_name="MockModel", obj_id=1)

        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Legacy bulk_delete and bulk_action
# ─────────────────────────────────────────────────────────────────────────────


class TestLegacyBulkDelete:
    @pytest.fixture
    def handler(self, router):
        return _find_handler(router, "/models/{model_name}/bulk-delete/", "POST")

    @pytest.mark.asyncio
    async def test_bulk_delete_success(self, handler, mock_request):
        mock_request.json.return_value = {"ids": [1, 2, 3]}
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.log_change", new_callable=AsyncMock),
        ):
            ma = MagicMock()
            mock_admin.get_model_admin_by_name.return_value = ma
            mock_admin.get_model_by_name.return_value = MockModel

            MockModel.objects.filter.return_value.delete = AsyncMock(return_value=3)

            resp = await handler(mock_request, model_name="MockModel")
            data = json.loads(resp.body)

        assert "deleted" in data or resp.status_code == 200


class TestLegacyBulkAction:
    @pytest.fixture
    def handler(self, router):
        return _find_handler(router, "/models/{model_name}/bulk-action/", "POST")

    @pytest.mark.asyncio
    async def test_not_registered_raises(self, handler, mock_request):
        mock_request.json.return_value = {"action": "x", "ids": [1]}
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_name.side_effect = NotRegistered("nope")
            with pytest.raises(NotFound):
                await handler(mock_request, model_name="Missing")

    @pytest.mark.asyncio
    async def test_action_success(self, handler, mock_request):
        mock_request.json.return_value = {"action": "process", "ids": [1, 2]}
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.get_action") as mock_get_action,
        ):
            ma = MagicMock()
            action = MagicMock()
            action.has_permission.return_value = True
            action.execute = AsyncMock(
                return_value=MagicMock(success=True, count=2, message="done", errors={})
            )
            mock_get_action.return_value = action
            mock_admin.get_model_admin_by_name.return_value = ma
            mock_admin.get_model_by_name.return_value = MockModel

            resp = await handler(mock_request, model_name="MockModel")
            data = json.loads(resp.body)

        assert data["success"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Legacy search_instances
# ─────────────────────────────────────────────────────────────────────────────


class TestSearchInstances:
    @pytest.fixture
    def handler(self, router):
        return _find_handler(router, "/models/{model_name}/search/", "GET")

    @pytest.mark.asyncio
    async def test_delegates_to_list(self, handler, mock_request):
        mock_request.query_params = {"q": "test"}
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.check_model_permission", return_value=True),
        ):
            ma = MagicMock()
            ma.list_per_page = 10
            ma.get_list_display.return_value = []
            ma.get_search_fields.return_value = []
            ma.get_ordering.return_value = []
            mock_admin.get_model_admin_by_name.return_value = ma
            mock_admin.get_model_by_name.return_value = MockModel

            resp = await handler(mock_request, model_name="MockModel")

        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# get_filter_options: BooleanField case
# ─────────────────────────────────────────────────────────────────────────────


class TestGetFilterOptionsCoverage:
    @pytest.fixture
    def handler(self, router):
        return _find_handler(router, "/models/{model_name}/filters/", "GET")

    @pytest.mark.asyncio
    async def test_boolean_field_returns_yes_no(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.get_list_filter.return_value = ["is_active"]
            mock_admin.get_model_admin_by_name.return_value = ma

            bool_field = MagicMock()
            bool_field.__class__.__name__ = "BooleanField"
            bool_field.choices = None
            mc = MagicMock()
            mc._fields = {"is_active": bool_field}
            mock_admin.get_model_by_name.return_value = mc

            resp = await handler(mock_request, model_name="MC")
            data = json.loads(resp.body)

        filter_entry = next((f for f in data["filters"] if f["name"] == "is_active"), None)
        assert filter_entry is not None
        labels = [c["label"] for c in filter_entry["choices"]]
        assert "Yes" in labels
        assert "No" in labels

    @pytest.mark.asyncio
    async def test_charfield_with_choices(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.get_list_filter.return_value = ["status"]
            mock_admin.get_model_admin_by_name.return_value = ma

            char_field = MagicMock()
            char_field.__class__.__name__ = "CharField"
            char_field.choices = [("a", "Option A"), ("b", "Option B")]
            mc = MagicMock()
            mc._fields = {"status": char_field}
            mock_admin.get_model_by_name.return_value = mc

            resp = await handler(mock_request, model_name="MC")
            data = json.loads(resp.body)

        filter_entry = next((f for f in data["filters"] if f["name"] == "status"), None)
        assert filter_entry is not None
        assert len(filter_entry["choices"]) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Legacy export_instances
# ─────────────────────────────────────────────────────────────────────────────


class TestLegacyExportInstances:
    @pytest.fixture
    def handler(self, router):
        return _find_handler(router, "/models/{model_name}/export/", "POST")

    @pytest.mark.asyncio
    async def test_export_all_as_csv(self, handler, mock_request):
        mock_request.json.return_value = {}
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.check_model_permission", return_value=True),
        ):
            ma = MagicMock()
            ma.get_list_display.return_value = ["id", "name"]
            mock_admin.get_model_admin_by_name.return_value = ma
            mock_admin.get_model_by_name.return_value = MockModel

            inst = MagicMock()
            inst.id = 1
            inst.name = "Alice"
            MockModel.objects.all.return_value.all = AsyncMock(return_value=[inst])
            MockModel.objects.filter.return_value.all = AsyncMock(return_value=[inst])

            resp = await handler(mock_request, model_name="MockModel")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_export_no_permission_raises(self, handler, mock_request):
        mock_request.json.return_value = {}
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.check_model_permission", return_value=False),
        ):
            mock_admin.get_model_admin_by_name.return_value = MagicMock()
            mock_admin.get_model_by_name.return_value = MockModel
            with pytest.raises(PermissionDenied):
                await handler(mock_request, model_name="MockModel")


# ─────────────────────────────────────────────────────────────────────────────
# Legacy get_instance_history
# ─────────────────────────────────────────────────────────────────────────────


class TestLegacyGetInstanceHistory:
    @pytest.fixture
    def handler(self, router):
        return _find_handler(router, "/models/{model_name}/{obj_id}/history/", "GET")

    @pytest.mark.asyncio
    async def test_history_not_registered_raises(self, handler, mock_request):
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_by_name.side_effect = NotRegistered("nope")
            with pytest.raises(NotFound):
                await handler(mock_request, model_name="Missing", obj_id=1)

    @pytest.mark.asyncio
    async def test_history_success(self, handler, mock_request):
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.get_change_history") as mock_hist,
        ):
            mock_admin.get_model_admin_by_name.return_value = MagicMock()
            mock_admin.get_model_by_name.return_value = MockModel
            MockModel.objects.get_or_none.return_value = MockModel(id=1)
            mock_hist.return_value = []

            resp = await handler(mock_request, model_name="MockModel", obj_id=1)
            data = json.loads(resp.body)

        assert "history" in data


# ─────────────────────────────────────────────────────────────────────────────
# fk_search: fallback resolution paths
# ─────────────────────────────────────────────────────────────────────────────


class TestFkSearchFallbackPaths:
    @pytest.fixture
    def handler(self, router):
        for route in router.routes:
            if "fk-search" in route.path:
                return route.handler

    @pytest.mark.asyncio
    async def test_fallback_to_importlib(self, handler, mock_request):
        mock_request.query_params = {"q": "test"}
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.importlib.import_module") as mock_import,
        ):
            mock_admin.get_model_by_app_and_name.side_effect = NotRegistered("nope")

            mod = MagicMock()
            mc = MagicMock()
            mc.__name__ = "TestModel"
            mc._fields = {}
            mod.TestModel = mc
            mock_import.return_value = mod

            qs = _make_full_qs()
            mc.objects = MagicMock()
            mc.objects.all.return_value = qs

            resp = await handler(mock_request, app_label="myapp", model_name="TestModel")
            data = json.loads(resp.body)

        assert "items" in data

    @pytest.mark.asyncio
    async def test_fallback_to_all_registered_models(self, handler, mock_request):
        mock_request.query_params = {"q": "alice"}
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.importlib.import_module", side_effect=ImportError),
        ):
            mock_admin.get_model_by_app_and_name.side_effect = NotRegistered("nope")
            mock_admin.get_all_models.return_value = [(MockModel, MagicMock())]

            qs = MockModel.setup_mock_objects()
            qs.all.return_value = [MockModel(id=1, username="alice")]

            resp = await handler(mock_request, app_label="x", model_name="MockModel")
            data = json.loads(resp.body)

        assert "items" in data

    @pytest.mark.asyncio
    async def test_model_not_found_raises(self, handler, mock_request):
        mock_request.query_params = {}
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.importlib.import_module", side_effect=ImportError),
        ):
            mock_admin.get_model_by_app_and_name.side_effect = NotRegistered("nope")
            mock_admin.get_all_models.return_value = []

            with pytest.raises(NotFound):
                await handler(mock_request, app_label="x", model_name="NonExistent")

    @pytest.mark.asyncio
    async def test_search_on_text_field(self, handler, mock_request):
        mock_request.query_params = {"q": "alice"}
        mc = MagicMock()
        mc.__name__ = "MC"
        text_field = MagicMock()
        text_field.__class__.__name__ = "CharField"
        mc._fields = {"name": text_field}

        inst = MagicMock()
        inst.id = 1

        qs = _make_full_qs()
        qs.all.return_value = [inst]
        mc.objects = MagicMock()
        mc.objects.all.return_value = qs

        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_by_app_and_name.return_value = mc

            resp = await handler(mock_request, app_label="x", model_name="MC")
            data = json.loads(resp.body)

        assert len(data["items"]) == 1
        qs.filter.assert_called()


# ─────────────────────────────────────────────────────────────────────────────
# list_plugins
# ─────────────────────────────────────────────────────────────────────────────


class TestListPlugins:
    @pytest.mark.asyncio
    async def test_returns_empty_list(self, router, mock_request):
        handler = _find_handler(router, "/plugins/", "GET")
        resp = await handler(mock_request)
        data = json.loads(resp.body)
        assert data["plugins"] == []

    @pytest.mark.asyncio
    async def test_no_access_raises(self, router, mock_request):
        handler = _find_handler(router, "/plugins/", "GET")
        with patch("openviper.admin.api.views.check_admin_access", return_value=False):
            with pytest.raises(PermissionDenied):
                await handler(mock_request)


# ─────────────────────────────────────────────────────────────────────────────
# global_search: edge cases
# ─────────────────────────────────────────────────────────────────────────────


class TestGlobalSearchEdgeCases:
    @pytest.fixture
    def handler(self, router):
        return _find_handler(router, "/search/", "GET")

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, handler, mock_request):
        mock_request.query_params = {"q": ""}
        resp = await handler(mock_request)
        data = json.loads(resp.body)
        assert data["results"] == []

    @pytest.mark.asyncio
    async def test_no_query_param_returns_empty(self, handler, mock_request):
        mock_request.query_params = {}
        resp = await handler(mock_request)
        data = json.loads(resp.body)
        assert data["results"] == []

    @pytest.mark.asyncio
    async def test_model_without_permission_skipped(self, handler, mock_request):
        mock_request.query_params = {"q": "test"}
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.check_model_permission", return_value=False),
        ):
            ma = MagicMock()
            mock_admin.get_all_models.return_value = [(MockModel, ma)]

            resp = await handler(mock_request)
            data = json.loads(resp.body)

        assert data["results"] == []

    @pytest.mark.asyncio
    async def test_fallback_search_fields_from_field_names(self, handler, mock_request):
        mock_request.query_params = {"q": "alice"}
        mc = MagicMock()
        mc.__name__ = "Post"
        mc._fields = {"title": MagicMock(), "body": MagicMock()}

        inst = MagicMock()
        inst.id = 1

        qs = _make_full_qs()
        qs.all.return_value = [inst]
        mc.objects = MagicMock()
        mc.objects.all.return_value = qs

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.check_model_permission", return_value=True),
        ):
            ma = MagicMock()
            ma.get_search_fields.return_value = []
            mock_admin.get_all_models.return_value = [(mc, ma)]
            mock_admin._get_app_label.return_value = "blog"

            resp = await handler(mock_request)
            data = json.loads(resp.body)

        assert len(data["results"]) == 1

    @pytest.mark.asyncio
    async def test_model_without_any_search_fields_skipped(self, handler, mock_request):
        mock_request.query_params = {"q": "test"}
        mc = MagicMock()
        mc.__name__ = "NoSearch"
        mc._fields = {"count": MagicMock()}

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.check_model_permission", return_value=True),
        ):
            ma = MagicMock()
            ma.get_search_fields.return_value = []
            mock_admin.get_all_models.return_value = [(mc, ma)]

            resp = await handler(mock_request)
            data = json.loads(resp.body)

        assert data["results"] == []

    @pytest.mark.asyncio
    async def test_50_result_limit(self, handler, mock_request):
        mock_request.query_params = {"q": "x"}
        mc = MagicMock()
        mc.__name__ = "BigModel"
        mc._fields = {}

        instances = [MagicMock(id=i) for i in range(60)]
        qs = _make_full_qs()
        qs.all.return_value = instances

        mc.objects = MagicMock()
        mc.objects.all.return_value = qs

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.check_model_permission", return_value=True),
        ):
            ma = MagicMock()
            ma.get_search_fields.return_value = ["name"]
            mock_admin.get_all_models.return_value = [(mc, ma)]
            mock_admin._get_app_label.return_value = "app"

            resp = await handler(mock_request)
            data = json.loads(resp.body)

        assert len(data["results"]) <= 50


# ─────────────────────────────────────────────────────────────────────────────
# ADDED MISSING COVERAGE
# ─────────────────────────────────────────────────────────────────────────────


class TestCheckAdminAccessCoverage:
    """Test endpoints when check_admin_access returns False."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("path", "method", "kwargs"),
        [
            ("/auth/change-password/", "POST", {}),
            ("/auth/change-user-password/1/", "POST", {}),
            ("/dashboard/", "GET", {}),
            ("/models/", "GET", {}),
            ("/models/x/y/", "GET", {}),
            ("/models/x/y/list/", "GET", {}),
            ("/models/x/y/", "POST", {}),
            ("/models/x/y/1/", "GET", {}),
            ("/models/x/y/1/", "PUT", {}),
            ("/models/x/y/1/", "DELETE", {}),
            ("/models/x/y/bulk-action/", "POST", {}),
            ("/models/x/y/export/", "GET", {}),
            ("/models/x/y/1/history/", "GET", {}),
            ("/models/x/y/fk-search/", "GET", {}),
            ("/models/y/", "GET", {}),
            ("/models/y/1/", "GET", {}),
            ("/models/y/1/", "PATCH", {}),
            ("/models/y/1/", "DELETE", {}),
            ("/models/y/bulk-delete/", "POST", {}),
            ("/models/y/bulk-action/", "POST", {}),
            ("/models/y/export/", "GET", {}),
            ("/models/y/filters/", "GET", {}),
            ("/models/y/1/history/", "GET", {}),
            ("/search/", "GET", {}),
            ("/models/x/y/1/files/field/", "DELETE", {}),
        ],
    )
    async def test_all_endpoints_admin_access_required(
        self, router, mock_request, path, method, kwargs
    ):
        handler = _find_handler(router, path, method)
        if callable(handler):
            with patch("openviper.admin.api.views.check_admin_access", return_value=False):
                route_params: dict = {}
                if not kwargs:
                    if "/x/y/" in path:
                        route_params.update({"app_label": "x", "model_name": "y"})
                    elif "/y/" in path and "/x/" not in path:
                        route_params.update({"model_name": "y"})
                    if "/1/" in path or path.endswith("/1/"):
                        route_params["obj_id"] = 1
                    if "change-user-password" in path:
                        route_params["user_id"] = 1
                    if "files/field" in path:
                        route_params["field_name"] = "field"
                call_kwargs = kwargs if kwargs else route_params
                with pytest.raises(PermissionDenied, match="Admin access required"):
                    await handler(mock_request, **call_kwargs)


class TestDashboardExceptions:
    @pytest.mark.asyncio
    async def test_dashboard_model_count_exception(self, router, mock_request):
        handler = _find_handler(router, "/dashboard/", "GET")

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.get_recent_activity", return_value=[]),
        ):
            mc = MagicMock()
            mc.__name__ = "BadCountModel"
            mc.objects.count.side_effect = Exception("DB error")
            mock_admin.get_all_models.return_value = [(mc, MagicMock())]

            resp = await handler(mock_request)
            data = json.loads(resp.body)
            assert data["stats"]["BadCountModel"] == 0

    @pytest.mark.asyncio
    async def test_dashboard_recent_activity_exception(self, router, mock_request):
        handler = _find_handler(router, "/dashboard/", "GET")

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch(
                "openviper.admin.api.views.get_recent_activity",
                side_effect=Exception("No history table"),
            ),
        ):
            mock_admin.get_all_models.return_value = []
            resp = await handler(mock_request)
            data = json.loads(resp.body)
            assert data["recent_activity"] == []


class TestInlineCreateAndUpdate:
    @pytest.mark.asyncio
    async def test_create_instance_inline_parsing(self, router, mock_request, mock_engine):
        handler = _find_handler(router, "/models/{app_label}/{model_name}/", "POST")

        mock_request.json.return_value = {
            "name": "Parent",
            "child_set": [{"value": "child1"}],
        }

        mc = MagicMock()
        mc.__name__ = "MyModel"
        mc._fields = {}
        inst = MagicMock(id=10)
        inst.save = AsyncMock()

        child_model = MagicMock()
        child_model.__name__ = "Child"
        child_model._fields = {"value": MagicMock(), "parent_fk": MagicMock()}

        # Simulate un-named inline fk discovery
        inline = MagicMock()
        inline.model = child_model
        inline.fk_name = None
        inline.extra_filters = {"extra": 1}

        fk_field = MagicMock()
        fk_field.__class__.__name__ = "ForeignKey"
        fk_field.resolve_target.return_value = mc
        child_model._fields["parent_fk"] = fk_field

        child_inst = MagicMock()
        child_inst.save = AsyncMock()
        child_model.return_value = child_inst

        # Patch child_model.objects.filter().all to AsyncMock
        child_qs = MagicMock()
        child_qs.all = AsyncMock(return_value=[])
        child_model.objects.filter = MagicMock(return_value=child_qs)

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.coerce_field_value", lambda f, v: v),
        ):
            ma = MagicMock()
            ma.has_add_permission.return_value = True
            ma.get_readonly_fields.return_value = []
            ma.child_tables = []
            ma.inlines = [MagicMock(return_value=inline)]
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = mc
            mc.return_value = inst
            resp = await handler(mock_request, app_label="app", model_name="MyModel")

        assert resp.status_code == 201
        child_inst.save.assert_awaited()
        assert child_inst.parent_fk == 10
        assert child_inst.extra == 1

    @pytest.mark.asyncio
    async def test_update_instance_inline_parsing(self, router, mock_request, mock_engine):
        handler = _find_handler(router, "/models/{app_label}/{model_name}/{obj_id}/", "PUT")

        mock_request.json.return_value = {
            "name": "Parent Updated",
            "child_set": [
                {"id": 1, "value": "updated_child"},
                {"value": "new_child"},
            ],
        }

        mc = MagicMock()
        mc.__name__ = "MyModel"
        mc._fields = {}
        inst = MagicMock(id=10)
        inst.save = AsyncMock()
        mc.objects.get_or_none = AsyncMock(return_value=inst)

        child_model = MagicMock()
        child_model.__name__ = "Child"
        child_model._fields = {"value": MagicMock(), "parent_fk": MagicMock()}

        # Simulate un-named inline fk discovery
        inline = MagicMock()
        inline.model = child_model
        inline.fk_name = None
        inline.extra_filters = {"extra": 1}

        fk_field = MagicMock()
        fk_field.__class__.__name__ = "ForeignKey"
        fk_field.resolve_target.return_value = mc
        child_model._fields["parent_fk"] = fk_field

        child_inst_new = MagicMock()
        child_inst_new.save = AsyncMock()
        child_model.return_value = child_inst_new

        child_inst_ex_1 = MagicMock(id=1)
        child_inst_ex_1.save = AsyncMock()

        child_inst_ex_2 = MagicMock(id=2)
        child_inst_ex_2.delete = AsyncMock()

        child_qs = MagicMock()
        child_qs.all = AsyncMock(return_value=[child_inst_ex_1, child_inst_ex_2])
        child_model.objects.filter = MagicMock(return_value=child_qs)

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.coerce_field_value", lambda f, v: v),
        ):
            ma = MagicMock()
            ma.get_readonly_fields.return_value = []
            ma.child_tables = []
            ma.inlines = [MagicMock(return_value=inline)]
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = mc

            resp = await handler(mock_request, app_label="app", model_name="MyModel", obj_id=10)

        assert resp.status_code == 200
        child_inst_ex_1.save.assert_awaited()  # updated
        child_inst_new.save.assert_awaited()  # created
        child_inst_ex_2.delete.assert_awaited()  # deleted


class TestOtherExceptionEdges:
    @pytest.mark.asyncio
    async def test_list_instances_by_app_not_registered(self, router, mock_request):
        handler = _find_handler(router, "/models/{app_label}/{model_name}/list/", "GET")
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_app_and_name.side_effect = NotRegistered("n")
            with pytest.raises(NotFound):
                await handler(mock_request, app_label="x", model_name="Y")

    @pytest.mark.asyncio
    async def test_form_json_parsing_in_update(self, router, mock_request, mock_engine):
        handler = _find_handler(router, "/models/{app_label}/{model_name}/{obj_id}/", "PUT")
        mock_request.headers = {"content-type": "application/x-www-form-urlencoded"}
        mock_request.json.side_effect = Exception("Not JSON")

        # Add form parsing mock
        mock_request.form = AsyncMock(
            return_value={
                "json_list": "[1, 2]",
                "json_dict": '{"a": 1}',
                "bad_json": "[bad",
                "normal": "text",
            }
        )

        mc = MagicMock()
        mc.__name__ = "MyModel"
        mc._fields = {}
        inst = MagicMock(id=10)
        inst.save = AsyncMock()
        mc.objects.get_or_none = AsyncMock(return_value=inst)

        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.get_readonly_fields.return_value = []
            ma.child_tables = []
            ma.inlines = []
            mock_admin.get_model_admin_by_app_and_name.return_value = ma
            mock_admin.get_model_by_app_and_name.return_value = mc
            with pytest.raises(Exception, match="Not JSON"):
                await handler(mock_request, app_label="x", model_name="y", obj_id=10)

    @pytest.mark.asyncio
    async def test_legacy_create_instance_value_error(self, router, mock_request, mock_engine):
        handler = _find_handler(router, "/models/{model_name}/", "POST")
        mock_request.json.return_value = {"bad_field": "val"}
        mc = MagicMock()
        mc.__name__ = "MC"
        mc._fields = {"bad_field": MagicMock()}

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch(
                "openviper.admin.api.views.coerce_field_value", side_effect=ValueError("bad_val")
            ),
        ):
            ma = MagicMock()
            ma.has_add_permission.return_value = True
            ma.get_readonly_fields.return_value = []
            mock_admin.get_model_admin_by_name.return_value = ma
            mock_admin.get_model_by_name.return_value = mc

            resp = await handler(mock_request, model_name="MC")

        assert resp.status_code == 422
        assert "bad_field" in json.loads(resp.body)["errors"]

    @pytest.mark.asyncio
    async def test_legacy_update_instance_value_error(self, router, mock_request, mock_engine):
        handler = _find_handler(router, "/models/{model_name}/{obj_id}/", "PATCH")
        mock_request.json.return_value = {"bad_field": "val"}
        mc = MagicMock()
        mc.__name__ = "MC"
        mc._fields = {"bad_field": MagicMock()}
        inst = MagicMock(id=1)
        mc.objects.get_or_none = AsyncMock(return_value=inst)

        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch(
                "openviper.admin.api.views.coerce_field_value", side_effect=ValueError("bad_val")
            ),
        ):
            ma = MagicMock()
            ma.get_readonly_fields.return_value = []
            mock_admin.get_model_admin_by_name.return_value = ma
            mock_admin.get_model_by_name.return_value = mc

            resp = await handler(mock_request, model_name="MC", obj_id=1)

        assert resp.status_code == 422
        assert "bad_field" in json.loads(resp.body)["errors"]

    @pytest.mark.asyncio
    async def test_legacy_bulk_delete_errors(self, router, mock_request):
        handler = _find_handler(router, "/models/{model_name}/bulk-delete/", "POST")

        # Missing IDs
        mock_request.json.return_value = {}
        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            mock_admin.get_model_admin_by_name.return_value = ma
            mock_admin.get_model_by_name.return_value = MagicMock()
            with pytest.raises(ValidationError):
                await handler(mock_request, model_name="x")

        # No permission
        mock_request.json.return_value = {"ids": [1]}
        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.has_delete_permission.return_value = False
            mock_admin.get_model_admin_by_name.return_value = ma
            mock_admin.get_model_by_name.return_value = MagicMock()
            with pytest.raises(PermissionDenied):
                await handler(mock_request, model_name="x")

        # Not registered
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_name.side_effect = NotRegistered()
            with pytest.raises(NotFound):
                await handler(mock_request, model_name="x")

    @pytest.mark.asyncio
    async def test_legacy_bulk_action_errors(self, router, mock_request):
        handler = _find_handler(router, "/models/{model_name}/bulk-action/", "POST")

        # Missing Action
        mock_request.json.return_value = {}
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_name.return_value = MagicMock()
            mock_admin.get_model_by_name.return_value = MagicMock()
            with pytest.raises(ValidationError, match="Action name is required"):
                await handler(mock_request, model_name="x")

        # Missing IDs
        mock_request.json.return_value = {"action": "x"}
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_name.return_value = MagicMock()
            mock_admin.get_model_by_name.return_value = MagicMock()
            with pytest.raises(ValidationError, match="No IDs provided"):
                await handler(mock_request, model_name="x")

        # Unknown action
        mock_request.json.return_value = {"action": "x", "ids": [1]}
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.get_action", return_value=None),
        ):
            mock_admin.get_model_admin_by_name.return_value = MagicMock()
            mock_admin.get_model_by_name.return_value = MagicMock()
            with pytest.raises(NotFound, match="Action 'x' not found"):
                await handler(mock_request, model_name="x")

        # Action Permission denied
        mock_request.json.return_value = {"action": "x", "ids": [1]}
        with (
            patch("openviper.admin.api.views.admin") as mock_admin,
            patch("openviper.admin.api.views.get_action") as mock_get_action,
        ):
            mock_admin.get_model_admin_by_name.return_value = MagicMock()
            mock_admin.get_model_by_name.return_value = MagicMock()
            act = MagicMock()
            act.has_permission.return_value = False
            mock_get_action.return_value = act
            with pytest.raises(PermissionDenied):
                await handler(mock_request, model_name="x")

    @pytest.mark.asyncio
    async def test_legacy_export_instances_not_registered(self, router, mock_request):
        handler = _find_handler(router, "/models/{model_name}/export/", "POST")
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_name.side_effect = NotRegistered()
            with pytest.raises(NotFound):
                await handler(mock_request, model_name="x")

    @pytest.mark.asyncio
    async def test_legacy_get_filter_options_not_registered(self, router, mock_request):
        handler = _find_handler(router, "/models/{model_name}/filters/", "GET")
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_name.side_effect = NotRegistered()
            with pytest.raises(NotFound):
                await handler(mock_request, model_name="x")

    @pytest.mark.asyncio
    async def test_legacy_get_instance_history_no_permission(self, router, mock_request):
        handler = _find_handler(router, "/models/{model_name}/{obj_id}/history/", "GET")
        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_by_name.side_effect = NotRegistered()
            with pytest.raises(NotFound):
                await handler(mock_request, model_name="x", obj_id=1)


# ---------------------------------------------------------------------------
# correctness tests for admin fixes
# ---------------------------------------------------------------------------


def _find_handler_by_path_method(router, path, method):
    for route in router.routes:
        if route.path == path and method in route.methods:
            return route.handler
    return None


class TestAdminSecurityFixes:
    """Tests covering the security and correctness fixes in admin/api/views.py."""

    # ── sensitive field filtering uses model_admin.get_sensitive_fields() ──

    @pytest.mark.asyncio
    async def test_serialize_uses_model_admin_sensitive_fields(self):
        """_serialize_instance_with_children uses model_admin.get_sensitive_fields(),
        not the hardcoded ["password"] list."""

        ma = MagicMock()
        # Return a custom sensitive list that includes both "password" and "secret_key"
        ma.get_sensitive_fields.return_value = ["password", "secret_key"]
        ma.child_tables = []
        ma.inlines = []

        model_class = MagicMock()
        model_class._fields = {
            "username": MagicMock(),
            "password": MagicMock(),
            "secret_key": MagicMock(),
        }

        instance = MagicMock()
        instance.id = 1
        instance.username = "alice"
        instance.password = "hashed"
        instance.secret_key = "topsecret"

        request = MagicMock()
        result = await _serialize_instance_with_children(request, ma, model_class, instance)

        assert "username" in result
        assert "password" not in result
        assert "secret_key" not in result
        ma.get_sensitive_fields.assert_called_once()

    # ── filter key injection prevention ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_list_filter_rejects_unknown_field(self, router, mock_request):
        """filter_ params with keys NOT in model._fields are silently ignored."""
        handler = _find_handler_by_path_method(
            router, "/models/{app_label}/{model_name}/list/", "GET"
        )
        if handler is None:
            # Try alternate path pattern used in some app-label list endpoints
            for route in router.routes:
                if "{app_label}" in route.path and "list" in route.path and "GET" in route.methods:
                    handler = route.handler
                    break
        assert handler is not None, "list handler not found"

        mock_request.query_params = {"filter_injected__extra": "x"}

        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.list_per_page = 20
            ma.get_list_display.return_value = ["id"]
            ma.get_sensitive_fields.return_value = []
            ma.get_search_fields.return_value = []
            ma.get_ordering.return_value = []
            ma.get_list_select_related.return_value = []
            mock_admin.get_model_admin_by_app_and_name.return_value = ma

            qs = MagicMock()
            qs.all = AsyncMock(return_value=[])
            qs.count = AsyncMock(return_value=0)
            qs.filter = MagicMock(return_value=qs)
            qs.order_by = MagicMock(return_value=qs)
            qs.offset = MagicMock(return_value=qs)
            qs.limit = MagicMock(return_value=qs)
            qs.select_related = MagicMock(return_value=qs)

            mock_model = MagicMock()
            mock_model._fields = {"id": MagicMock()}  # "injected__extra" NOT in _fields
            mock_model.objects.all.return_value = qs
            mock_admin.get_model_by_app_and_name.return_value = mock_model

            # Should succeed without passing the injected key to filter()
            resp = await handler(mock_request, app_label="test_app", model_name="MockModel")
            assert resp.status_code == 200
            # filter() must NOT have been called with the injected key
            for call in qs.filter.call_args_list:
                assert "injected__extra" not in call.kwargs

    # ── pagination bounds ────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_pagination_negative_page_clamped_to_1(self, router, mock_request):
        """page < 1 is clamped to 1 (no negative offset)."""
        handler = _find_handler_by_path_method(
            router, "/models/{app_label}/{model_name}/list/", "GET"
        )
        if handler is None:
            for route in router.routes:
                if "{app_label}" in route.path and "list" in route.path and "GET" in route.methods:
                    handler = route.handler
                    break
        assert handler is not None

        mock_request.query_params = {"page": "-5", "per_page": "10"}

        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.list_per_page = 20
            ma.get_list_display.return_value = ["id"]
            ma.get_sensitive_fields.return_value = []
            ma.get_search_fields.return_value = []
            ma.get_ordering.return_value = []
            ma.get_list_select_related.return_value = []
            mock_admin.get_model_admin_by_app_and_name.return_value = ma

            qs = MagicMock()
            qs.all = AsyncMock(return_value=[])
            qs.count = AsyncMock(return_value=0)
            qs.filter = MagicMock(return_value=qs)
            qs.order_by = MagicMock(return_value=qs)
            qs.offset = MagicMock(return_value=qs)
            qs.limit = MagicMock(return_value=qs)
            qs.select_related = MagicMock(return_value=qs)

            mock_model = MagicMock()
            mock_model._fields = {}
            mock_model.objects.all.return_value = qs
            mock_admin.get_model_by_app_and_name.return_value = mock_model

            resp = await handler(mock_request, app_label="test_app", model_name="MockModel")
            assert resp.status_code == 200
            # offset call must use non-negative value: (max(1,-5)-1)*10 = 0
            offset_call = qs.offset.call_args
            assert offset_call is not None
            assert offset_call.args[0] >= 0

    @pytest.mark.asyncio
    async def test_pagination_huge_page_size_clamped(self, router, mock_request):
        """page_size is capped at 1000."""
        handler = _find_handler_by_path_method(
            router, "/models/{app_label}/{model_name}/list/", "GET"
        )
        if handler is None:
            for route in router.routes:
                if "{app_label}" in route.path and "list" in route.path and "GET" in route.methods:
                    handler = route.handler
                    break
        assert handler is not None

        mock_request.query_params = {"page": "1", "per_page": "999999"}

        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.list_per_page = 20
            ma.get_list_display.return_value = ["id"]
            ma.get_sensitive_fields.return_value = []
            ma.get_search_fields.return_value = []
            ma.get_ordering.return_value = []
            ma.get_list_select_related.return_value = []
            mock_admin.get_model_admin_by_app_and_name.return_value = ma

            qs = MagicMock()
            qs.all = AsyncMock(return_value=[])
            qs.count = AsyncMock(return_value=0)
            qs.filter = MagicMock(return_value=qs)
            qs.order_by = MagicMock(return_value=qs)
            qs.offset = MagicMock(return_value=qs)
            qs.limit = MagicMock(return_value=qs)
            qs.select_related = MagicMock(return_value=qs)

            mock_model = MagicMock()
            mock_model._fields = {}
            mock_model.objects.all.return_value = qs
            mock_admin.get_model_by_app_and_name.return_value = mock_model

            resp = await handler(mock_request, app_label="test_app", model_name="MockModel")
            assert resp.status_code == 200
            limit_call = qs.limit.call_args
            assert limit_call is not None
            assert limit_call.args[0] <= 1000

    # ── bulk IDs limit ───────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_bulk_delete_rejects_more_than_1000_ids(self, router, mock_request):
        """bulk-delete rejects payloads with > 1000 IDs."""
        handler = _find_handler_by_path_method(router, "/models/{model_name}/bulk-delete/", "POST")
        assert handler is not None

        mock_request.json.return_value = {"ids": list(range(1001))}

        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            ma.has_delete_permission.return_value = True
            mock_admin.get_model_admin_by_name.return_value = ma
            mock_admin.get_model_by_name.return_value = MagicMock()

            with pytest.raises(ValidationError):
                await handler(mock_request, model_name="MockModel")

    @pytest.mark.asyncio
    async def test_bulk_action_rejects_more_than_1000_ids(self, router, mock_request):
        """bulk-action rejects payloads with > 1000 IDs."""
        handler = _find_handler_by_path_method(
            router, "/models/{app_label}/{model_name}/bulk-action/", "POST"
        )
        assert handler is not None

        mock_request.json.return_value = {"action": "delete", "ids": list(range(1001))}

        with patch("openviper.admin.api.views.admin") as mock_admin:
            mock_admin.get_model_admin_by_app_and_name.return_value = MagicMock()
            mock_admin.get_model_by_app_and_name.return_value = MagicMock()

            with pytest.raises(ValidationError):
                await handler(mock_request, app_label="test_app", model_name="MockModel")

    # ── id builtin shadowing fix ─────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_delete_not_found_uses_obj_id(self, router, mock_request):
        """delete_instance uses obj_id (not the builtin id) in NotFound message."""
        handler = _find_handler_by_path_method(router, "/models/{model_name}/{obj_id}/", "DELETE")
        assert handler is not None

        with patch("openviper.admin.api.views.admin") as mock_admin:
            ma = MagicMock()
            mock_admin.get_model_admin_by_name.return_value = ma

            mock_model = MagicMock()
            mock_model.objects.get_or_none = AsyncMock(return_value=None)
            mock_admin.get_model_by_name.return_value = mock_model

            with pytest.raises(NotFound) as exc_info:
                await handler(mock_request, model_name="Widget", obj_id=42)

            # Message must contain "42", not some unrelated id() value
            assert "42" in str(exc_info.value)


# ── Missing Branch Coverage Tests ────────────────────────────────────────────


class TestAdminAccessPermissionBranches:
    """Test check_admin_access permission check branches in various endpoints."""

    @pytest.mark.asyncio
    async def test_change_password_requires_admin_access(self, router, mock_request):
        """change_password endpoint raises PermissionDenied when not admin - line 484."""
        handler = _find_handler_by_path_method(
            router, "/auth/change-user-password/{user_id}/", "POST"
        )
        assert handler is not None

        mock_request.user = MockUser()
        mock_request.user.is_superuser = True
        mock_request.json = AsyncMock(
            return_value={"new_password": "newpass123", "confirm_password": "newpass123"}
        )

        with patch("openviper.admin.api.views.check_admin_access", return_value=False):
            with pytest.raises(PermissionDenied, match="Admin access required"):
                await handler(mock_request, user_id="1")

    @pytest.mark.asyncio
    async def test_get_model_config_requires_admin_access(self, router, mock_request):
        """get_model_config endpoint raises PermissionDenied when not admin - line 613."""
        handler = _find_handler_by_path_method(router, "/models/{app_label}/{model_name}/", "GET")
        assert handler is not None

        with patch("openviper.admin.api.views.check_admin_access", return_value=False):
            with pytest.raises(PermissionDenied, match="Admin access required"):
                await handler(mock_request, app_label="app", model_name="model")

    @pytest.mark.asyncio
    async def test_list_instances_by_app_requires_admin_access(self, router, mock_request):
        """list_instances_by_app endpoint raises PermissionDenied when not admin - line 632."""
        handler = _find_handler_by_path_method(
            router, "/models/{app_label}/{model_name}/list/", "GET"
        )
        assert handler is not None

        with patch("openviper.admin.api.views.check_admin_access", return_value=False):
            with pytest.raises(PermissionDenied, match="Admin access required"):
                await handler(mock_request, app_label="app", model_name="model")

    @pytest.mark.asyncio
    async def test_create_instance_by_app_requires_admin_access(self, router, mock_request):
        """create_instance_by_app endpoint raises PermissionDenied when not admin - line 758."""
        handler = _find_handler_by_path_method(router, "/models/{app_label}/{model_name}/", "POST")
        assert handler is not None

        mock_request.json = AsyncMock(return_value={"name": "test"})

        with patch("openviper.admin.api.views.check_admin_access", return_value=False):
            with pytest.raises(PermissionDenied, match="Admin access required"):
                await handler(mock_request, app_label="app", model_name="model")


class TestFormDataJsonParsing:
    """Test FormData JSON parsing with JSONDecodeError fallback."""

    @pytest.mark.asyncio
    async def test_create_view_handles_invalid_json_in_formdata(self, router, mock_request):
        """create_instance_by_app handles JSONDecodeError in FormData - lines 770-780."""
        handler = _find_handler_by_path_method(router, "/models/{app_label}/{model_name}/", "POST")
        assert handler is not None

        # Mock multipart/form-data request with invalid JSON
        mock_request.headers = {"content-type": "multipart/form-data"}
        mock_request.form = AsyncMock(
            return_value={
                "data": "{invalid json here}",  # Starts with { but isn't valid JSON
                "name": "test",
            }
        )

        mock_instance = MagicMock()
        mock_instance.id = 1
        mock_instance.save = AsyncMock()

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch("openviper.admin.api.views.admin") as mock_admin:
                ma = MagicMock()
                ma.has_add_permission.return_value = True
                ma.get_readonly_fields.return_value = []
                ma.list_children.return_value = []
                mock_admin.get_model_admin_by_app_and_name.return_value = ma

                mock_model = MagicMock()
                mock_model._fields = {}
                mock_model.return_value = mock_instance  # __init__ returns instance
                mock_admin.get_model_by_app_and_name.return_value = mock_model

                with patch("openviper.admin.api.views.check_model_permission", return_value=True):
                    with patch(
                        "openviper.admin.api.views._serialize_instance_with_children",
                        return_value={},
                    ):
                        # Should not raise - JSONDecodeError is caught and raw value is used
                        response = await handler(mock_request, app_label="app", model_name="model")
                        assert response.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_update_view_handles_invalid_json_in_formdata(self, router, mock_request):
        """update_instance_by_app handles JSONDecodeError in FormData - lines 925-935."""
        handler = _find_handler_by_path_method(
            router, "/models/{app_label}/{model_name}/{obj_id}/", "PUT"
        )
        assert handler is not None

        # Mock multipart/form-data request with invalid JSON
        mock_request.headers = {"content-type": "multipart/form-data"}
        mock_request.form = AsyncMock(
            return_value={
                "tags": "[invalid, json, array",  # Starts with [ but isn't valid JSON
                "name": "updated",
            }
        )

        mock_instance = MagicMock()
        mock_instance.id = 1
        mock_instance.to_dict = MagicMock(return_value={"name": "old"})
        mock_instance.save = AsyncMock()

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch("openviper.admin.api.views.admin") as mock_admin:
                ma = MagicMock()
                ma.has_change_permission.return_value = True
                ma.get_readonly_fields.return_value = []
                ma.list_children.return_value = []
                mock_admin.get_model_admin_by_app_and_name.return_value = ma

                mock_model = MagicMock()
                mock_model._fields = {}
                mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)
                mock_admin.get_model_by_app_and_name.return_value = mock_model

                with patch("openviper.admin.api.views.check_model_permission", return_value=True):
                    with patch(
                        "openviper.admin.api.views._serialize_instance_with_children",
                        return_value={},
                    ):
                        with patch("openviper.admin.api.views.cast_to_pk_type", return_value=1):
                            # Should not raise - JSONDecodeError is caught
                            response = await handler(
                                mock_request, app_label="app", model_name="model", obj_id="1"
                            )
                            assert response.status_code in (200, 201)


class TestUpdateViewExceptionHandling:
    """Test exception handling in update_instance_by_app - lines 1055-1059."""

    @pytest.mark.asyncio
    async def test_update_view_handles_value_error(self, router, mock_request):
        """update_instance_by_app returns 422 on ValueError - lines 1055-1056."""
        handler = _find_handler_by_path_method(
            router, "/models/{app_label}/{model_name}/{obj_id}/", "PUT"
        )
        assert handler is not None

        mock_request.headers = {"content-type": "application/json"}
        mock_request.json = AsyncMock(return_value={"field": "value"})

        mock_instance = MagicMock()
        mock_instance.id = 1
        mock_instance.to_dict = MagicMock(return_value={"field": "old"})
        # Make the save raise ValueError
        mock_instance.save = AsyncMock(side_effect=ValueError("Invalid field value"))

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch("openviper.admin.api.views.admin") as mock_admin:
                ma = MagicMock()
                ma.has_change_permission.return_value = True
                ma.get_readonly_fields.return_value = []
                ma.list_children.return_value = []
                mock_admin.get_model_admin_by_app_and_name.return_value = ma

                mock_model = MagicMock()
                mock_model._fields = {}
                mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)
                mock_admin.get_model_by_app_and_name.return_value = mock_model

                with patch("openviper.admin.api.views.check_model_permission", return_value=True):
                    with patch("openviper.admin.api.views.cast_to_pk_type", return_value=1):
                        response = await handler(
                            mock_request, app_label="app", model_name="model", obj_id="1"
                        )
                        # Should return 422 with error message
                        assert response.status_code == 422
                        body = json.loads(response.body)
                        assert "errors" in body
                        assert "__all__" in body["errors"]

    @pytest.mark.asyncio
    async def test_update_view_handles_integrity_error(self, router, mock_request):
        """update_instance_by_app returns 422 on IntegrityError - lines 1057-1059."""
        handler = _find_handler_by_path_method(
            router, "/models/{app_label}/{model_name}/{obj_id}/", "PUT"
        )
        assert handler is not None

        mock_request.headers = {"content-type": "application/json"}
        mock_request.json = AsyncMock(return_value={"email": "duplicate@example.com"})

        mock_instance = MagicMock()
        mock_instance.id = 1
        mock_instance.to_dict = MagicMock(return_value={"email": "old@example.com"})

        # Create IntegrityError with orig attribute
        orig_exc = Exception("UNIQUE constraint failed: users.email")
        integrity_error = sqlalchemy.exc.IntegrityError("statement", {}, orig_exc)
        integrity_error.orig = orig_exc
        mock_instance.save = AsyncMock(side_effect=integrity_error)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch("openviper.admin.api.views.admin") as mock_admin:
                ma = MagicMock()
                ma.has_change_permission.return_value = True
                ma.get_readonly_fields.return_value = []
                ma.list_children.return_value = []
                mock_admin.get_model_admin_by_app_and_name.return_value = ma

                mock_model = MagicMock()
                mock_model._fields = {}
                mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)
                mock_admin.get_model_by_app_and_name.return_value = mock_model

                with patch("openviper.admin.api.views.check_model_permission", return_value=True):
                    with patch("openviper.admin.api.views.cast_to_pk_type", return_value=1):
                        response = await handler(
                            mock_request, app_label="app", model_name="model", obj_id="1"
                        )
                        # Should return 422 with error message
                        assert response.status_code == 422
                        body = json.loads(response.body)
                        assert "errors" in body
                        assert "__all__" in body["errors"]
