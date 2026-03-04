"""Additional tests to cover remaining uncovered lines in admin/api/views.py."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.admin.api.views import (
    _serialize_instance_with_children,
    get_admin_router,
)
from openviper.exceptions import NotFound, PermissionDenied, ValidationError

# ---------------------------------------------------------------------------
# Helpers (duplicated from main test file for independence)
# ---------------------------------------------------------------------------


def _get_handler(router, name: str):
    for route in router.routes:
        if route.handler.__name__ == name:
            return route.handler
    return None


def _mock_request(json_data=None, query_params=None, user=None):
    req = MagicMock(name="request")
    req.json = AsyncMock(return_value=json_data or {})
    req.query_params = query_params or {}
    if user is None:
        user = MagicMock()
        user.id = 1
        user.username = "admin"
        user.email = "admin@example.com"
        user.is_staff = True
        user.is_superuser = True
    req.user = user
    return req


def _make_router():
    return get_admin_router()


def _make_qs(items=None, total=0, delete_count=0):
    qs = MagicMock()
    qs.filter.return_value = qs
    qs.order_by.return_value = qs
    qs.offset.return_value = qs
    qs.limit.return_value = qs
    qs.count = AsyncMock(return_value=total)
    qs.all = AsyncMock(return_value=items or [])
    qs.delete = AsyncMock(return_value=delete_count)
    return qs


# ---------------------------------------------------------------------------
# _serialize_instance_with_children – child table path (lines 87-122)
# ---------------------------------------------------------------------------


class TestSerializeWithChildren:
    @pytest.mark.asyncio
    async def test_child_records_included_in_response(self):
        """Lines 87-122: child table records are fetched and serialized."""
        child_record = MagicMock()
        child_record.id = 10
        child_record.title = "Child 1"

        child_qs = MagicMock()
        child_qs.filter.return_value = child_qs
        child_qs.all = AsyncMock(return_value=[child_record])

        child_model = MagicMock()
        child_model.__name__ = "Comment"
        child_model._fields = {}
        child_model.objects.filter.return_value = child_qs

        inline = MagicMock()
        inline.model = child_model
        inline.fk_name = "article_id"
        inline.extra_filters = {}
        inline.fields = ["title"]

        inline_class = MagicMock(return_value=inline)

        model_admin = MagicMock()
        model_admin.child_tables = [inline_class]
        model_admin.inlines = []

        model_class = MagicMock()
        model_class._fields = {}
        model_class.__name__ = "Article"

        instance = MagicMock()
        instance.id = 1

        result = await _serialize_instance_with_children(
            _mock_request(), model_admin, model_class, instance
        )

        assert "comment_set" in result
        assert len(result["comment_set"]) == 1
        assert result["comment_set"][0]["title"] == "Child 1"

    @pytest.mark.asyncio
    async def test_child_fk_auto_discovered(self):
        """Lines 92-97: fk_name auto-discovery when not set."""
        child_record = MagicMock()
        child_record.id = 5
        child_record.name = "Auto FK"

        child_qs = MagicMock()
        child_qs.filter.return_value = child_qs
        child_qs.all = AsyncMock(return_value=[child_record])

        # Build a fake ForeignKey field that points to model_class
        model_class = MagicMock()
        model_class.__name__ = "Article"
        model_class._fields = {}

        fk_field = MagicMock()
        fk_field.__class__.__name__ = "ForeignKey"
        fk_field.resolve_target.return_value = model_class

        child_model = MagicMock()
        child_model.__name__ = "Tag"
        child_model._fields = {"article_fk": fk_field}
        child_model.objects.filter.return_value = child_qs

        inline = MagicMock()
        inline.model = child_model
        inline.fk_name = ""  # empty → auto-discover
        inline.fields = ["name"]
        inline.extra_filters = {}

        inline_class = MagicMock(return_value=inline)
        model_admin = MagicMock()
        model_admin.child_tables = [inline_class]
        model_admin.inlines = []

        instance = MagicMock()
        instance.id = 2

        result = await _serialize_instance_with_children(
            _mock_request(), model_admin, model_class, instance
        )

        assert "tag_set" in result

    @pytest.mark.asyncio
    async def test_child_with_extra_filters(self):
        """Line 102-103: extra_filters merged into child queryset filter."""
        child_qs = MagicMock()
        child_qs.filter.return_value = child_qs
        child_qs.all = AsyncMock(return_value=[])

        child_model = MagicMock()
        child_model.__name__ = "Tag"
        child_model._fields = {}
        child_model.objects.filter.return_value = child_qs

        inline = MagicMock()
        inline.model = child_model
        inline.fk_name = "parent_id"
        inline.extra_filters = {"active": True}
        inline.fields = []

        inline_class = MagicMock(return_value=inline)
        model_admin = MagicMock()
        model_admin.child_tables = [inline_class]
        model_admin.inlines = []

        model_class = MagicMock()
        model_class._fields = {}
        model_class.__name__ = "Article"

        instance = MagicMock()
        instance.id = 3

        result = await _serialize_instance_with_children(
            _mock_request(), model_admin, model_class, instance
        )

        # filter called with merged keys
        call_kwargs = child_model.objects.filter.call_args[1]
        assert call_kwargs.get("active") is True
        assert call_kwargs.get("parent_id") == 3

    @pytest.mark.asyncio
    async def test_child_datetime_isoformat(self):
        """Lines 114-115: child field with isoformat() is serialized."""
        dt = datetime(2024, 6, 1, 12, 0, 0)

        child_record = MagicMock()
        child_record.id = 9
        child_record.created_at = dt

        child_qs = MagicMock()
        child_qs.filter.return_value = child_qs
        child_qs.all = AsyncMock(return_value=[child_record])

        child_model = MagicMock()
        child_model.__name__ = "Item"
        child_model._fields = {}
        child_model.objects.filter.return_value = child_qs

        inline = MagicMock()
        inline.model = child_model
        inline.fk_name = "parent_id"
        inline.extra_filters = {}
        inline.fields = ["created_at"]

        inline_class = MagicMock(return_value=inline)
        model_admin = MagicMock()
        model_admin.child_tables = [inline_class]
        model_admin.inlines = []

        model_class = MagicMock()
        model_class._fields = {}
        model_class.__name__ = "Parent"

        instance = MagicMock()
        instance.id = 1

        result = await _serialize_instance_with_children(
            _mock_request(), model_admin, model_class, instance
        )

        assert result["item_set"][0]["created_at"] == dt.isoformat()


# ---------------------------------------------------------------------------
# admin_change_user_password – validation paths (lines 332, 335, 338)
# ---------------------------------------------------------------------------


class TestAdminChangeUserPasswordValidation:
    @pytest.mark.asyncio
    async def test_missing_new_password_raises_validation_error(self):
        router = _make_router()
        handler = _get_handler(router, "admin_change_user_password")

        req = _mock_request(json_data={"confirm_password": "something"})
        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with pytest.raises(ValidationError, match="required"):
                await handler(req, user_id=1)

    @pytest.mark.asyncio
    async def test_password_mismatch_raises_validation_error(self):
        router = _make_router()
        handler = _get_handler(router, "admin_change_user_password")

        req = _mock_request(
            json_data={"new_password": "password1", "confirm_password": "password2"}
        )
        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with pytest.raises(ValidationError, match="do not match"):
                await handler(req, user_id=1)

    @pytest.mark.asyncio
    async def test_short_new_password_raises_validation_error(self):
        router = _make_router()
        handler = _get_handler(router, "admin_change_user_password")

        req = _mock_request(json_data={"new_password": "short", "confirm_password": "short"})
        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with pytest.raises(ValidationError, match="8 characters"):
                await handler(req, user_id=1)


# ---------------------------------------------------------------------------
# admin_dashboard – model count exception path (lines 366-367, 374)
# ---------------------------------------------------------------------------


class TestAdminDashboardExtra:
    @pytest.mark.asyncio
    async def test_model_count_exception_yields_zero(self):
        """Lines 366-367: if model.objects.count() raises, stats[model] = 0."""
        router = _make_router()
        handler = _get_handler(router, "admin_dashboard")

        failing_model = MagicMock()
        failing_model.__name__ = "BrokenModel"
        failing_model.objects.count = AsyncMock(side_effect=RuntimeError("DB error"))
        mock_admin_obj = MagicMock()

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_all_models",
                return_value=[(failing_model, mock_admin_obj)],
            ):
                with patch(
                    "openviper.admin.api.views.get_recent_activity",
                    new_callable=AsyncMock,
                    return_value=[],
                ):
                    response = await handler(_mock_request())

        body = json.loads(response.body)
        assert body["stats"]["BrokenModel"] == 0

    @pytest.mark.asyncio
    async def test_recent_activity_records_appended(self):
        """Line 374: activity records are serialized into response."""
        router = _make_router()
        handler = _get_handler(router, "admin_dashboard")

        activity = MagicMock()
        activity.id = 1
        activity.model_name = "MyModel"
        activity.action = "ADD"
        activity.object_id = 1
        activity.object_repr = "MyModel #1"
        activity.changed_by_username = "admin"
        activity.change_message = "Added item"
        activity.change_time = datetime(2024, 1, 1)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch("openviper.admin.api.views.admin.get_all_models", return_value=[]):
                with patch(
                    "openviper.admin.api.views.get_recent_activity",
                    new_callable=AsyncMock,
                    return_value=[activity],
                ):
                    response = await handler(_mock_request())

        body = json.loads(response.body)
        assert len(body["recent_activity"]) == 1
        assert body["recent_activity"][0]["model_name"] == "MyModel"


# ---------------------------------------------------------------------------
# list_instances_by_app – filter / sort / serialization paths
# ---------------------------------------------------------------------------


class TestListInstancesByAppExtra:
    def _setup(self, instances=None, total=1):
        mock_instance = MagicMock()
        mock_instance.id = 1
        mock_instance.name = "Test"

        mock_model_admin = MagicMock()
        mock_model_admin.list_per_page = 20
        mock_model_admin.get_list_display.return_value = ["name"]
        mock_model_admin.get_search_fields.return_value = ["name"]
        mock_model_admin.get_ordering.return_value = ["-id"]

        qs = _make_qs(items=instances or [mock_instance], total=total)
        mock_model = MagicMock()
        mock_model.objects.all.return_value = qs
        return mock_model_admin, mock_model, qs

    @pytest.mark.asyncio
    async def test_filter_prefix_params_applied(self):
        """Lines 498-502: filter_ prefix params are collected and applied."""
        router = _make_router()
        handler = _get_handler(router, "list_instances_by_app")

        mock_model_admin, mock_model, qs = self._setup()

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        await handler(
                            _mock_request(query_params={"filter_status": "active"}),
                            app_label="a",
                            model_name="X",
                        )

        qs.filter.assert_called_with(status="active")

    @pytest.mark.asyncio
    async def test_ordering_from_model_admin_applied(self):
        """Lines 507-511: when no sort param, model_admin.get_ordering is used."""
        router = _make_router()
        handler = _get_handler(router, "list_instances_by_app")

        mock_model_admin, mock_model, qs = self._setup()
        mock_model_admin.get_ordering.return_value = ["-created_at"]

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        await handler(
                            _mock_request(query_params={}),
                            app_label="a",
                            model_name="X",
                        )

        qs.order_by.assert_called_with("-created_at")

    @pytest.mark.asyncio
    async def test_explicit_ordering_param_used(self):
        """Line 507: explicit 'ordering' query param takes precedence."""
        router = _make_router()
        handler = _get_handler(router, "list_instances_by_app")

        mock_model_admin, mock_model, qs = self._setup()

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        await handler(
                            _mock_request(query_params={"ordering": "name"}),
                            app_label="a",
                            model_name="X",
                        )

        qs.order_by.assert_called_with("name")

    @pytest.mark.asyncio
    async def test_value_isoformat_serialized(self):
        """Lines 541-544: datetime field values are isoformatted in response."""
        router = _make_router()
        handler = _get_handler(router, "list_instances_by_app")

        dt = datetime(2024, 3, 15)
        mock_instance = MagicMock()
        mock_instance.id = 1
        mock_instance.created_at = dt

        mock_model_admin = MagicMock()
        mock_model_admin.list_per_page = 20
        mock_model_admin.get_list_display.return_value = ["created_at"]
        mock_model_admin.get_search_fields.return_value = []
        mock_model_admin.get_ordering.return_value = []

        qs = _make_qs(items=[mock_instance], total=1)
        mock_model = MagicMock()
        mock_model.objects.all.return_value = qs

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        response = await handler(_mock_request(), app_label="a", model_name="X")

        body = json.loads(response.body)
        assert body["items"][0]["created_at"] == dt.isoformat()

    @pytest.mark.asyncio
    async def test_non_primitive_value_converted_to_str(self):
        """Lines 544-546: non-primitive values get str() in list serialization."""
        router = _make_router()
        handler = _get_handler(router, "list_instances_by_app")

        class Obj:
            def __str__(self):
                return "obj_str"

        mock_instance = MagicMock()
        mock_instance.id = 1
        mock_instance.data = Obj()

        mock_model_admin = MagicMock()
        mock_model_admin.list_per_page = 20
        mock_model_admin.get_list_display.return_value = ["data"]
        mock_model_admin.get_search_fields.return_value = []
        mock_model_admin.get_ordering.return_value = []

        qs = _make_qs(items=[mock_instance])
        mock_model = MagicMock()
        mock_model.objects.all.return_value = qs

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        response = await handler(_mock_request(), app_label="a", model_name="X")

        body = json.loads(response.body)
        assert body["items"][0]["data"] == "obj_str"


# ---------------------------------------------------------------------------
# create_instance_by_app – error paths and field coercion
# ---------------------------------------------------------------------------


class TestCreateInstanceByAppExtra:
    def _setup_create(self):
        mock_instance = MagicMock()
        mock_instance.id = 99
        mock_instance.save = AsyncMock()

        mock_model_admin = MagicMock()
        mock_model_admin.has_add_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = []
        mock_model_admin.child_tables = []
        mock_model_admin.inlines = []

        mock_model = MagicMock()
        mock_model._fields = {}
        mock_model.return_value = mock_instance

        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

        return mock_model_admin, mock_model, mock_instance, mock_engine

    @pytest.mark.asyncio
    async def test_value_error_returns_422(self):
        """Lines 630-631: ValueError during save returns 422 with errors."""
        router = _make_router()
        handler = _get_handler(router, "create_instance_by_app")

        mock_model_admin, mock_model, mock_instance, mock_engine = self._setup_create()
        mock_instance.save = AsyncMock(side_effect=ValueError("bad value"))

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.get_engine",
                        new_callable=AsyncMock,
                        return_value=mock_engine,
                    ):
                        response = await handler(
                            _mock_request(json_data={"title": "X"}),
                            app_label="a",
                            model_name="Article",
                        )

        assert response.status_code == 422
        body = json.loads(response.body)
        assert "errors" in body

    @pytest.mark.asyncio
    async def test_readonly_field_skipped(self):
        """Line 587: readonly fields are skipped during field coercion."""
        router = _make_router()
        handler = _get_handler(router, "create_instance_by_app")

        mock_model_admin, mock_model, mock_instance, mock_engine = self._setup_create()
        mock_model_admin.get_readonly_fields.return_value = ["created_at"]

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.get_engine",
                        new_callable=AsyncMock,
                        return_value=mock_engine,
                    ):
                        with patch(
                            "openviper.admin.api.views._serialize_instance_with_children",
                            new_callable=AsyncMock,
                            return_value={"id": 99},
                        ):
                            await handler(
                                _mock_request(json_data={"created_at": "2024-01-01", "title": "X"}),
                                app_label="a",
                                model_name="Article",
                            )

        # 'created_at' should not be in the kwargs passed to model_class
        call_kwargs = mock_model.call_args[1] if mock_model.call_args else {}
        assert "created_at" not in call_kwargs

    @pytest.mark.asyncio
    async def test_field_coercion_applied(self):
        """Line 589: fields present in model._fields get coerce_field_value."""
        router = _make_router()
        handler = _get_handler(router, "create_instance_by_app")

        mock_model_admin, mock_model, mock_instance, mock_engine = self._setup_create()
        fake_field = MagicMock()
        mock_model._fields = {"count": fake_field}

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.get_engine",
                        new_callable=AsyncMock,
                        return_value=mock_engine,
                    ):
                        with patch(
                            "openviper.admin.api.views.coerce_field_value",
                            return_value=42,
                        ) as mock_coerce:
                            with patch(
                                "openviper.admin.api.views._serialize_instance_with_children",
                                new_callable=AsyncMock,
                                return_value={"id": 99},
                            ):
                                await handler(
                                    _mock_request(json_data={"count": "42"}),
                                    app_label="a",
                                    model_name="Article",
                                )

        mock_coerce.assert_called_once_with(fake_field, "42")


# ---------------------------------------------------------------------------
# get_instance_by_app – no view permission path (lines 664-665, 672)
# ---------------------------------------------------------------------------


class TestGetInstanceByAppExtra:
    @pytest.mark.asyncio
    async def test_no_view_permission_raises_permission_denied(self):
        """Lines 664-665, 672: has_view_permission=False raises PermissionDenied."""
        router = _make_router()
        handler = _get_handler(router, "get_instance_by_app")

        mock_instance = MagicMock()
        mock_model_admin = MagicMock()
        mock_model_admin.has_view_permission.return_value = False
        mock_model = MagicMock()
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with pytest.raises(PermissionDenied):
                        await handler(
                            _mock_request(), app_label="a", model_name="Article", obj_id=1
                        )


# ---------------------------------------------------------------------------
# update_instance_by_app – full coverage (lines 696-822)
# ---------------------------------------------------------------------------


class TestUpdateInstanceByApp:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "update_instance_by_app")

        with patch("openviper.admin.api.views.check_admin_access", return_value=False):
            with pytest.raises(PermissionDenied):
                await handler(_mock_request(), app_label="a", model_name="X", obj_id=1)

    @pytest.mark.asyncio
    async def test_not_registered_raises_not_found(self):
        from openviper.admin.registry import NotRegistered

        router = _make_router()
        handler = _get_handler(router, "update_instance_by_app")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                side_effect=NotRegistered("x"),
            ):
                with pytest.raises(NotFound):
                    await handler(_mock_request(), app_label="a", model_name="X", obj_id=1)

    @pytest.mark.asyncio
    async def test_instance_not_found_raises_not_found(self):
        router = _make_router()
        handler = _get_handler(router, "update_instance_by_app")

        mock_model = MagicMock()
        mock_model.objects.get_or_none = AsyncMock(return_value=None)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=MagicMock(),
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with pytest.raises(NotFound):
                        await handler(_mock_request(), app_label="a", model_name="X", obj_id=99)

    @pytest.mark.asyncio
    async def test_no_change_permission_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "update_instance_by_app")

        mock_instance = MagicMock()
        mock_model_admin = MagicMock()
        mock_model_admin.has_change_permission.return_value = False
        mock_model = MagicMock()
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with pytest.raises(PermissionDenied):
                        await handler(_mock_request(), app_label="a", model_name="X", obj_id=1)

    @pytest.mark.asyncio
    async def test_successful_update_returns_200(self):
        """Lines 696-822: successful full update path."""
        router = _make_router()
        handler = _get_handler(router, "update_instance_by_app")

        mock_instance = MagicMock()
        mock_instance.id = 1
        mock_instance.save = AsyncMock()

        mock_model_admin = MagicMock()
        mock_model_admin.has_change_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = []
        mock_model_admin.child_tables = []
        mock_model_admin.inlines = []

        mock_model = MagicMock()
        mock_model._fields = {}
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.get_engine",
                        new_callable=AsyncMock,
                        return_value=mock_engine,
                    ):
                        with patch(
                            "openviper.admin.api.views._serialize_instance_with_children",
                            new_callable=AsyncMock,
                            return_value={"id": 1, "title": "Updated"},
                        ):
                            with patch(
                                "openviper.admin.api.views.log_change", new_callable=AsyncMock
                            ):
                                with patch(
                                    "openviper.admin.api.views.compute_changes",
                                    return_value={"title": ("Old", "Updated")},
                                ):
                                    response = await handler(
                                        _mock_request(json_data={"title": "Updated"}),
                                        app_label="a",
                                        model_name="Article",
                                        obj_id=1,
                                    )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_value_error_returns_422(self):
        """Line 800: ValueError during save returns 422."""
        router = _make_router()
        handler = _get_handler(router, "update_instance_by_app")

        mock_instance = MagicMock()
        mock_instance.id = 1
        mock_instance.save = AsyncMock(side_effect=ValueError("bad"))

        mock_model_admin = MagicMock()
        mock_model_admin.has_change_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = []
        mock_model_admin.child_tables = []
        mock_model_admin.inlines = []

        mock_model = MagicMock()
        mock_model._fields = {}
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        mock_engine = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.get_engine",
                        new_callable=AsyncMock,
                        return_value=mock_engine,
                    ):
                        response = await handler(
                            _mock_request(json_data={"title": "x"}),
                            app_label="a",
                            model_name="Article",
                            obj_id=1,
                        )

        assert response.status_code == 422


# ---------------------------------------------------------------------------
# delete_instance_by_app – NotRegistered path (lines 835-836)
# ---------------------------------------------------------------------------


class TestDeleteInstanceByAppExtra:
    @pytest.mark.asyncio
    async def test_not_registered_raises_not_found(self):
        from openviper.admin.registry import NotRegistered

        router = _make_router()
        handler = _get_handler(router, "delete_instance_by_app")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                side_effect=NotRegistered("not found"),
            ):
                with pytest.raises(NotFound):
                    await handler(_mock_request(), app_label="a", model_name="X", obj_id=1)


# ---------------------------------------------------------------------------
# bulk_action_by_app – NotRegistered path (lines 870-871)
# ---------------------------------------------------------------------------


class TestBulkActionByAppExtra:
    @pytest.mark.asyncio
    async def test_not_registered_raises_not_found(self):
        from openviper.admin.registry import NotRegistered

        router = _make_router()
        handler = _get_handler(router, "bulk_action_by_app")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                side_effect=NotRegistered("x"),
            ):
                with pytest.raises(NotFound):
                    await handler(_mock_request(), app_label="a", model_name="X")

    @pytest.mark.asyncio
    async def test_action_no_permission_raises_permission_denied(self):
        """Line 888: action without permission raises PermissionDenied."""
        router = _make_router()
        handler = _get_handler(router, "bulk_action_by_app")

        mock_model = MagicMock()
        mock_model.objects.filter.return_value = _make_qs()

        mock_action = MagicMock()
        mock_action.has_permission.return_value = False

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=MagicMock(),
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch("openviper.admin.api.views.get_action", return_value=mock_action):
                        with pytest.raises(PermissionDenied):
                            await handler(
                                _mock_request(json_data={"action": "delete_selected", "ids": [1]}),
                                app_label="a",
                                model_name="X",
                            )


# ---------------------------------------------------------------------------
# export_instances_by_app – ids param and datetime (lines 914-915, 944)
# ---------------------------------------------------------------------------


class TestExportInstancesByAppExtra:
    @pytest.mark.asyncio
    async def test_not_registered_raises_not_found(self):
        from openviper.admin.registry import NotRegistered

        router = _make_router()
        handler = _get_handler(router, "export_instances_by_app")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                side_effect=NotRegistered("x"),
            ):
                with pytest.raises(NotFound):
                    await handler(_mock_request(), app_label="a", model_name="X")

    @pytest.mark.asyncio
    async def test_ids_param_filters_queryset(self):
        """Lines 921-922, 927: ids param filters instances."""
        router = _make_router()
        handler = _get_handler(router, "export_instances_by_app")

        mock_instance = MagicMock()
        mock_instance.id = 3
        mock_instance.title = "X"

        mock_model_admin = MagicMock()
        mock_model_admin.get_list_display.return_value = ["title"]

        qs = _make_qs(items=[mock_instance])
        mock_model = MagicMock()
        mock_model.objects.filter.return_value = qs

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        response = await handler(
                            _mock_request(query_params={"ids": "3,5"}),
                            app_label="a",
                            model_name="Article",
                        )

        assert response.status_code == 200
        # filter called with id__in=[3,5]
        mock_model.objects.filter.assert_called_with(id__in=[3, 5])

    @pytest.mark.asyncio
    async def test_datetime_field_isoformatted_in_csv(self):
        """Line 944: datetime values in export are isoformatted."""
        router = _make_router()
        handler = _get_handler(router, "export_instances_by_app")

        dt = datetime(2025, 1, 10)
        mock_instance = MagicMock()
        mock_instance.id = 1
        mock_instance.created_at = dt

        mock_model_admin = MagicMock()
        mock_model_admin.get_list_display.return_value = ["created_at"]

        qs = _make_qs(items=[mock_instance])
        mock_model = MagicMock()
        mock_model.objects.all.return_value = qs

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        response = await handler(
                            _mock_request(query_params={}),
                            app_label="a",
                            model_name="Article",
                        )

        assert dt.isoformat() in response.body.decode()


# ---------------------------------------------------------------------------
# get_instance_history_by_app – NotRegistered (lines 970-971)
# ---------------------------------------------------------------------------


class TestGetInstanceHistoryByAppExtra:
    @pytest.mark.asyncio
    async def test_not_registered_raises_not_found(self):
        from openviper.admin.registry import NotRegistered

        router = _make_router()
        handler = _get_handler(router, "get_instance_history_by_app")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_by_app_and_name",
                side_effect=NotRegistered("x"),
            ):
                with pytest.raises(NotFound):
                    await handler(_mock_request(), app_label="a", model_name="X", obj_id=1)


# ---------------------------------------------------------------------------
# list_instances (legacy) – extra paths
# ---------------------------------------------------------------------------


class TestListInstancesExtra:
    def _setup(self):
        mock_instance = MagicMock()
        mock_instance.id = 1
        mock_instance.title = "Test Article"

        mock_model_admin = MagicMock()
        mock_model_admin.list_per_page = 10
        mock_model_admin.get_list_display.return_value = ["title"]
        mock_model_admin.get_search_fields.return_value = ["title"]
        mock_model_admin.get_ordering.return_value = []

        qs = _make_qs(items=[mock_instance], total=1)
        mock_model = MagicMock()
        mock_model.objects.all.return_value = qs
        return mock_model_admin, mock_model, qs, mock_instance

    @pytest.mark.asyncio
    async def test_no_view_permission_returns_permission_denied_response(self):
        """Lines 1008-1020: no view permission returns empty result with flag."""
        router = _make_router()
        handler = _get_handler(router, "list_instances")

        mock_model_admin, mock_model, qs, _ = self._setup()

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=False
                    ):
                        response = await handler(_mock_request(), model_name="Article")

        body = json.loads(response.body)
        assert body["permission_denied"] is True

    @pytest.mark.asyncio
    async def test_q_param_triggers_search(self):
        """Lines 1026-1035: 'q' param applies queryset filter."""
        router = _make_router()
        handler = _get_handler(router, "list_instances")

        mock_model_admin, mock_model, qs, _ = self._setup()

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        await handler(
                            _mock_request(query_params={"q": "foo"}), model_name="Article"
                        )

        qs.filter.assert_called_with(title__contains="foo")

    @pytest.mark.asyncio
    async def test_filter_prefix_applied(self):
        """Lines 1037-1045: filter_ prefix params applied."""
        router = _make_router()
        handler = _get_handler(router, "list_instances")

        mock_model_admin, mock_model, qs, _ = self._setup()
        mock_model_admin.get_search_fields.return_value = []

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        await handler(
                            _mock_request(query_params={"filter_status": "active"}),
                            model_name="Article",
                        )

        qs.filter.assert_called_with(status="active")

    @pytest.mark.asyncio
    async def test_sort_param_applied(self):
        """Line 1050: explicit sort param used."""
        router = _make_router()
        handler = _get_handler(router, "list_instances")

        mock_model_admin, mock_model, qs, _ = self._setup()
        mock_model_admin.get_search_fields.return_value = []

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        await handler(
                            _mock_request(query_params={"sort": "title"}), model_name="Article"
                        )

        qs.order_by.assert_called_with("title")

    @pytest.mark.asyncio
    async def test_model_admin_ordering_applied(self):
        """Line 1054: model_admin.get_ordering used when no sort param."""
        router = _make_router()
        handler = _get_handler(router, "list_instances")

        mock_model_admin, mock_model, qs, _ = self._setup()
        mock_model_admin.get_ordering.return_value = ["-name"]
        mock_model_admin.get_search_fields.return_value = []

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        await handler(_mock_request(), model_name="Article")

        qs.order_by.assert_called_with("-name")

    @pytest.mark.asyncio
    async def test_isoformat_value_in_list(self):
        """Lines 1075-1076: datetime value serialized to isoformat in list."""
        router = _make_router()
        handler = _get_handler(router, "list_instances")

        dt = datetime(2025, 2, 1)
        mock_instance = MagicMock()
        mock_instance.id = 5
        mock_instance.ts = dt

        mock_model_admin = MagicMock()
        mock_model_admin.list_per_page = 10
        mock_model_admin.get_list_display.return_value = ["ts"]
        mock_model_admin.get_search_fields.return_value = []
        mock_model_admin.get_ordering.return_value = []

        qs = _make_qs(items=[mock_instance], total=1)
        mock_model = MagicMock()
        mock_model.objects.all.return_value = qs

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        response = await handler(_mock_request(), model_name="Article")

        body = json.loads(response.body)
        assert body["items"][0]["ts"] == dt.isoformat()

    @pytest.mark.asyncio
    async def test_non_primitive_value_to_str(self):
        """Line 1078: non-primitive value converted to str."""
        router = _make_router()
        handler = _get_handler(router, "list_instances")

        class ObjVal:
            def __str__(self):
                return "myobj"

        mock_instance = MagicMock()
        mock_instance.id = 5
        mock_instance.data = ObjVal()

        mock_model_admin = MagicMock()
        mock_model_admin.list_per_page = 10
        mock_model_admin.get_list_display.return_value = ["data"]
        mock_model_admin.get_search_fields.return_value = []
        mock_model_admin.get_ordering.return_value = []

        qs = _make_qs(items=[mock_instance], total=1)
        mock_model = MagicMock()
        mock_model.objects.all.return_value = qs

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        response = await handler(_mock_request(), model_name="Article")

        body = json.loads(response.body)
        assert body["items"][0]["data"] == "myobj"


# ---------------------------------------------------------------------------
# create_instance (legacy) – extra paths
# ---------------------------------------------------------------------------


class TestCreateInstanceExtra:
    @pytest.mark.asyncio
    async def test_no_add_permission_raises_permission_denied(self):
        """Lines 1105-1106."""
        router = _make_router()
        handler = _get_handler(router, "create_instance")

        mock_model_admin = MagicMock()
        mock_model_admin.has_add_permission.return_value = False

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=MagicMock()
                ):
                    with pytest.raises(PermissionDenied):
                        await handler(_mock_request(), model_name="Article")

    @pytest.mark.asyncio
    async def test_field_coercion_and_log_change(self):
        """Lines 1117-1143: field coercion applied and log_change called."""
        router = _make_router()
        handler = _get_handler(router, "create_instance")

        mock_instance = MagicMock()
        mock_instance.id = 20
        mock_instance.count = 5
        mock_instance.save = AsyncMock()

        fake_field = MagicMock()
        mock_model_admin = MagicMock()
        mock_model_admin.has_add_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = []

        mock_model = MagicMock()
        mock_model._fields = {"count": fake_field}
        mock_model.return_value = mock_instance

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch(
                        "openviper.admin.api.views.coerce_field_value", return_value=5
                    ) as mock_coerce:
                        with patch(
                            "openviper.admin.api.views.log_change", new_callable=AsyncMock
                        ) as mock_log:
                            response = await handler(
                                _mock_request(json_data={"count": "5"}), model_name="Article"
                            )

        assert response.status_code == 201
        mock_coerce.assert_called_once_with(fake_field, "5")
        mock_log.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_isoformat_in_response(self):
        """Line 1151: datetime field value isoformatted in create response."""
        router = _make_router()
        handler = _get_handler(router, "create_instance")

        dt = datetime(2024, 5, 20)
        mock_instance = MagicMock()
        mock_instance.id = 30
        mock_instance.ts = dt
        mock_instance.save = AsyncMock()

        mock_model_admin = MagicMock()
        mock_model_admin.has_add_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = []

        mock_model = MagicMock()
        mock_model._fields = {"ts": MagicMock()}
        mock_model.return_value = mock_instance

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch("openviper.admin.api.views.coerce_field_value", return_value=dt):
                        with patch("openviper.admin.api.views.log_change", new_callable=AsyncMock):
                            response = await handler(
                                _mock_request(json_data={"ts": dt.isoformat()}),
                                model_name="Article",
                            )

        body = json.loads(response.body)
        assert body["ts"] == dt.isoformat()


# ---------------------------------------------------------------------------
# get_instance (legacy) – extra paths (lines 1163-1180)
# ---------------------------------------------------------------------------


class TestGetInstanceExtra:
    @pytest.mark.asyncio
    async def test_no_view_permission_raises_permission_denied(self):
        """Lines 1163-1180: has_view_permission=False raises PermissionDenied."""
        router = _make_router()
        handler = _get_handler(router, "get_instance")

        mock_instance = MagicMock()
        mock_model_admin = MagicMock()
        mock_model_admin.has_view_permission.return_value = False
        mock_model = MagicMock()
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with pytest.raises(PermissionDenied):
                        await handler(_mock_request(), model_name="Article", obj_id=1)

    @pytest.mark.asyncio
    async def test_successful_get_instance(self):
        """Lines 1163-1187: successful retrieval serializes instance."""
        router = _make_router()
        handler = _get_handler(router, "get_instance")

        mock_instance = MagicMock()
        mock_instance.id = 42
        mock_model_admin = MagicMock()
        mock_model_admin.has_view_permission.return_value = True
        mock_model_admin.get_model_info.return_value = {"name": "Article"}
        mock_model_admin.get_readonly_fields.return_value = []
        mock_model_admin.get_fieldsets.return_value = []
        mock_model = MagicMock()
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch(
                        "openviper.admin.api.views._serialize_instance_with_children",
                        new_callable=AsyncMock,
                        return_value={"id": 42},
                    ):
                        response = await handler(_mock_request(), model_name="Article", obj_id=42)

        body = json.loads(response.body)
        assert body["instance"]["id"] == 42


# ---------------------------------------------------------------------------
# update_instance (legacy PATCH) – full coverage (lines 1192-1254)
# ---------------------------------------------------------------------------


class TestUpdateInstance:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "update_instance")

        with patch("openviper.admin.api.views.check_admin_access", return_value=False):
            with pytest.raises(PermissionDenied):
                await handler(_mock_request(), model_name="X", obj_id=1)

    @pytest.mark.asyncio
    async def test_instance_not_found_raises_not_found(self):
        router = _make_router()
        handler = _get_handler(router, "update_instance")

        mock_model = MagicMock()
        mock_model.objects.get_or_none = AsyncMock(return_value=None)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name", return_value=MagicMock()
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with pytest.raises(NotFound):
                        await handler(_mock_request(), model_name="X", obj_id=99)

    @pytest.mark.asyncio
    async def test_no_change_permission_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "update_instance")

        mock_instance = MagicMock()
        mock_model_admin = MagicMock()
        mock_model_admin.has_change_permission.return_value = False
        mock_model = MagicMock()
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with pytest.raises(PermissionDenied):
                        await handler(_mock_request(), model_name="X", obj_id=1)

    @pytest.mark.asyncio
    async def test_successful_update_returns_200(self):
        """Lines 1192-1254: successful patch update."""
        router = _make_router()
        handler = _get_handler(router, "update_instance")

        mock_instance = MagicMock()
        mock_instance.id = 7
        mock_instance.save = AsyncMock()

        mock_model_admin = MagicMock()
        mock_model_admin.has_change_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = []

        mock_model = MagicMock()
        mock_model._fields = {}
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch("openviper.admin.api.views.log_change", new_callable=AsyncMock):
                        with patch(
                            "openviper.admin.api.views.compute_changes",
                            return_value={"title": ("Old", "New")},
                        ):
                            response = await handler(
                                _mock_request(json_data={"title": "New"}),
                                model_name="Article",
                                obj_id=7,
                            )

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# delete_instance (legacy) – extra paths (lines 1260-1273)
# ---------------------------------------------------------------------------


class TestDeleteInstanceExtra:
    @pytest.mark.asyncio
    async def test_not_registered_raises_not_found(self):
        from openviper.admin.registry import NotRegistered

        router = _make_router()
        handler = _get_handler(router, "delete_instance")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                side_effect=NotRegistered("x"),
            ):
                with pytest.raises(NotFound):
                    await handler(_mock_request(), model_name="X", obj_id=1)

    @pytest.mark.asyncio
    async def test_instance_not_found_raises_not_found(self):
        router = _make_router()
        handler = _get_handler(router, "delete_instance")

        mock_model = MagicMock()
        mock_model.objects.get_or_none = AsyncMock(return_value=None)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name", return_value=MagicMock()
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with pytest.raises(NotFound):
                        await handler(_mock_request(), model_name="X", obj_id=99)

    @pytest.mark.asyncio
    async def test_no_delete_permission_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "delete_instance")

        mock_instance = MagicMock()
        mock_model_admin = MagicMock()
        mock_model_admin.has_delete_permission.return_value = False
        mock_model = MagicMock()
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with pytest.raises(PermissionDenied):
                        await handler(_mock_request(), model_name="X", obj_id=1)


# ---------------------------------------------------------------------------
# bulk_delete (lines 1295-1332)
# ---------------------------------------------------------------------------


class TestBulkDelete:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "bulk_delete")

        with patch("openviper.admin.api.views.check_admin_access", return_value=False):
            with pytest.raises(PermissionDenied):
                await handler(_mock_request(), model_name="X")

    @pytest.mark.asyncio
    async def test_not_registered_raises_not_found(self):
        from openviper.admin.registry import NotRegistered

        router = _make_router()
        handler = _get_handler(router, "bulk_delete")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                side_effect=NotRegistered("x"),
            ):
                with pytest.raises(NotFound):
                    await handler(_mock_request(), model_name="X")

    @pytest.mark.asyncio
    async def test_empty_ids_raises_validation_error(self):
        router = _make_router()
        handler = _get_handler(router, "bulk_delete")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name", return_value=MagicMock()
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=MagicMock()
                ):
                    with pytest.raises(ValidationError):
                        await handler(_mock_request(json_data={"ids": []}), model_name="X")

    @pytest.mark.asyncio
    async def test_no_delete_permission_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "bulk_delete")

        mock_model_admin = MagicMock()
        mock_model_admin.has_delete_permission.return_value = False

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=MagicMock()
                ):
                    with pytest.raises(PermissionDenied):
                        await handler(_mock_request(json_data={"ids": [1, 2]}), model_name="X")

    @pytest.mark.asyncio
    async def test_successful_bulk_delete(self):
        """Lines 1313-1331: successful bulk delete returns count."""
        router = _make_router()
        handler = _get_handler(router, "bulk_delete")

        qs = _make_qs(delete_count=3)
        mock_model = MagicMock()
        mock_model.objects.filter.return_value = qs

        mock_model_admin = MagicMock()
        mock_model_admin.has_delete_permission.return_value = True

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch("openviper.admin.api.views.log_change", new_callable=AsyncMock):
                        response = await handler(
                            _mock_request(json_data={"ids": [1, 2, 3]}), model_name="Article"
                        )

        body = json.loads(response.body)
        assert body["count"] == 3


# ---------------------------------------------------------------------------
# bulk_action (legacy) – full coverage (lines 1337-1379)
# ---------------------------------------------------------------------------


class TestBulkAction:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "bulk_action")

        with patch("openviper.admin.api.views.check_admin_access", return_value=False):
            with pytest.raises(PermissionDenied):
                await handler(_mock_request(), model_name="X")

    @pytest.mark.asyncio
    async def test_not_registered_raises_not_found(self):
        from openviper.admin.registry import NotRegistered

        router = _make_router()
        handler = _get_handler(router, "bulk_action")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                side_effect=NotRegistered("x"),
            ):
                with pytest.raises(NotFound):
                    await handler(_mock_request(), model_name="X")

    @pytest.mark.asyncio
    async def test_missing_action_raises_validation_error(self):
        router = _make_router()
        handler = _get_handler(router, "bulk_action")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name", return_value=MagicMock()
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=MagicMock()
                ):
                    with pytest.raises(ValidationError):
                        await handler(_mock_request(json_data={"ids": [1]}), model_name="X")

    @pytest.mark.asyncio
    async def test_missing_ids_raises_validation_error(self):
        router = _make_router()
        handler = _get_handler(router, "bulk_action")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name", return_value=MagicMock()
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=MagicMock()
                ):
                    with pytest.raises(ValidationError):
                        await handler(
                            _mock_request(json_data={"action": "delete_all"}), model_name="X"
                        )

    @pytest.mark.asyncio
    async def test_action_not_found_raises_not_found(self):
        router = _make_router()
        handler = _get_handler(router, "bulk_action")

        mock_model = MagicMock()
        mock_model.objects.filter.return_value = _make_qs()

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name", return_value=MagicMock()
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch("openviper.admin.api.views.get_action", return_value=None):
                        with pytest.raises(NotFound):
                            await handler(
                                _mock_request(json_data={"action": "noop", "ids": [1]}),
                                model_name="X",
                            )

    @pytest.mark.asyncio
    async def test_no_permission_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "bulk_action")

        mock_action = MagicMock()
        mock_action.has_permission.return_value = False
        mock_model = MagicMock()
        mock_model.objects.filter.return_value = _make_qs()

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name", return_value=MagicMock()
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch("openviper.admin.api.views.get_action", return_value=mock_action):
                        with pytest.raises(PermissionDenied):
                            await handler(
                                _mock_request(json_data={"action": "act", "ids": [1]}),
                                model_name="X",
                            )

    @pytest.mark.asyncio
    async def test_successful_bulk_action(self):
        """Lines 1366-1379: successful legacy bulk action."""
        router = _make_router()
        handler = _get_handler(router, "bulk_action")

        result = MagicMock()
        result.success = True
        result.count = 3
        result.message = "Done"
        result.errors = []

        mock_action = MagicMock()
        mock_action.has_permission.return_value = True
        mock_action.execute = AsyncMock(return_value=result)

        mock_model = MagicMock()
        mock_model.objects.filter.return_value = _make_qs()

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name", return_value=MagicMock()
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch("openviper.admin.api.views.get_action", return_value=mock_action):
                        response = await handler(
                            _mock_request(json_data={"action": "act", "ids": [1, 2, 3]}),
                            model_name="X",
                        )

        body = json.loads(response.body)
        assert body["success"] is True
        assert body["count"] == 3


# ---------------------------------------------------------------------------
# search_instances – delegates to list_instances (line 1387)
# ---------------------------------------------------------------------------


class TestSearchInstances:
    @pytest.mark.asyncio
    async def test_delegates_to_list_instances(self):
        """Line 1387: search_instances just calls list_instances."""
        router = _make_router()
        handler = _get_handler(router, "search_instances")

        mock_model_admin = MagicMock()
        mock_model_admin.list_per_page = 10
        mock_model_admin.get_list_display.return_value = []
        mock_model_admin.get_search_fields.return_value = []
        mock_model_admin.get_ordering.return_value = []

        qs = _make_qs()
        mock_model = MagicMock()
        mock_model.objects.all.return_value = qs

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        response = await handler(_mock_request(), model_name="Article")

        body = json.loads(response.body)
        assert "items" in body


# ---------------------------------------------------------------------------
# get_filter_options – BooleanField and no-choices paths (lines 1406-1426)
# ---------------------------------------------------------------------------


class TestGetFilterOptionsExtra:
    @pytest.mark.asyncio
    async def test_not_registered_raises_not_found(self):
        from openviper.admin.registry import NotRegistered

        router = _make_router()
        handler = _get_handler(router, "get_filter_options")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                side_effect=NotRegistered("x"),
            ):
                with pytest.raises(NotFound):
                    await handler(_mock_request(), model_name="X")

    @pytest.mark.asyncio
    async def test_boolean_field_gets_yes_no_choices(self):
        """Lines 1416-1420: BooleanField gets Yes/No options."""
        router = _make_router()
        handler = _get_handler(router, "get_filter_options")

        mock_field = MagicMock()
        mock_field.__class__.__name__ = "BooleanField"
        del mock_field.choices  # no choices attribute

        mock_model_admin = MagicMock()
        mock_model_admin.get_list_filter.return_value = ["is_active"]
        mock_model = MagicMock()
        mock_model._fields = {"is_active": mock_field}

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        response = await handler(_mock_request(), model_name="Article")

        body = json.loads(response.body)
        assert len(body["filters"]) == 1
        choices = body["filters"][0]["choices"]
        assert any(c["label"] == "Yes" for c in choices)
        assert any(c["label"] == "No" for c in choices)

    @pytest.mark.asyncio
    async def test_field_without_choices_gets_empty_list(self):
        """Line 1424: field without choices gets empty choices list."""
        router = _make_router()
        handler = _get_handler(router, "get_filter_options")

        mock_field = MagicMock()
        mock_field.__class__.__name__ = "CharField"
        mock_field.choices = []  # falsy → fall through to empty

        mock_model_admin = MagicMock()
        mock_model_admin.get_list_filter.return_value = ["name"]
        mock_model = MagicMock()
        mock_model._fields = {"name": mock_field}

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        response = await handler(_mock_request(), model_name="Article")

        body = json.loads(response.body)
        assert body["filters"][0]["choices"] == []


# ---------------------------------------------------------------------------
# export_instances (legacy POST) – full coverage (lines 1435-1482)
# ---------------------------------------------------------------------------


class TestExportInstances:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "export_instances")

        with patch("openviper.admin.api.views.check_admin_access", return_value=False):
            with pytest.raises(PermissionDenied):
                await handler(_mock_request(), model_name="Article")

    @pytest.mark.asyncio
    async def test_not_registered_raises_not_found(self):
        from openviper.admin.registry import NotRegistered

        router = _make_router()
        handler = _get_handler(router, "export_instances")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                side_effect=NotRegistered("x"),
            ):
                with pytest.raises(NotFound):
                    await handler(_mock_request(), model_name="X")

    @pytest.mark.asyncio
    async def test_no_view_permission_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "export_instances")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name", return_value=MagicMock()
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=MagicMock()
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=False
                    ):
                        with pytest.raises(PermissionDenied):
                            await handler(_mock_request(), model_name="Article")

    @pytest.mark.asyncio
    async def test_returns_csv_with_ids(self):
        """Lines 1447-1481: builds CSV from specific ids."""
        router = _make_router()
        handler = _get_handler(router, "export_instances")

        mock_instance = MagicMock()
        mock_instance.id = 7
        mock_instance.name = "Test"

        mock_model_admin = MagicMock()
        mock_model_admin.get_list_display.return_value = ["name"]

        qs = _make_qs(items=[mock_instance])
        mock_model = MagicMock()
        mock_model.objects.filter.return_value = qs

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        response = await handler(
                            _mock_request(json_data={"ids": [7]}), model_name="Article"
                        )

        assert response.status_code == 200
        assert "text/csv" in response.headers.get("Content-Type", "")

    @pytest.mark.asyncio
    async def test_datetime_field_isoformatted_in_csv(self):
        """Line 1468: datetime values in CSV are isoformatted."""
        router = _make_router()
        handler = _get_handler(router, "export_instances")

        dt = datetime(2025, 3, 1)
        mock_instance = MagicMock()
        mock_instance.id = 1
        mock_instance.ts = dt

        mock_model_admin = MagicMock()
        mock_model_admin.get_list_display.return_value = ["ts"]

        qs = _make_qs(items=[mock_instance])
        mock_model = MagicMock()
        mock_model.objects.all.return_value = qs

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        response = await handler(_mock_request(json_data={}), model_name="Article")

        assert dt.isoformat() in response.body.decode()


# ---------------------------------------------------------------------------
# get_instance_history (legacy) – full coverage (lines 1489-1518)
# ---------------------------------------------------------------------------


class TestGetInstanceHistoryLegacy:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "get_instance_history")

        with patch("openviper.admin.api.views.check_admin_access", return_value=False):
            with pytest.raises(PermissionDenied):
                await handler(_mock_request(), model_name="X", obj_id=1)

    @pytest.mark.asyncio
    async def test_not_registered_raises_not_found(self):
        from openviper.admin.registry import NotRegistered

        router = _make_router()
        handler = _get_handler(router, "get_instance_history")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_by_name",
                side_effect=NotRegistered("x"),
            ):
                with pytest.raises(NotFound):
                    await handler(_mock_request(), model_name="X", obj_id=1)

    @pytest.mark.asyncio
    async def test_instance_not_found_raises_not_found(self):
        router = _make_router()
        handler = _get_handler(router, "get_instance_history")

        mock_model = MagicMock()
        mock_model.objects.get_or_none = AsyncMock(return_value=None)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
            ):
                with pytest.raises(NotFound):
                    await handler(_mock_request(), model_name="X", obj_id=99)

    @pytest.mark.asyncio
    async def test_returns_history(self):
        """Lines 1503-1518: returns history records."""
        router = _make_router()
        handler = _get_handler(router, "get_instance_history")

        mock_instance = MagicMock()
        mock_model = MagicMock()
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        record = MagicMock()
        record.id = 1
        record.action = "change"
        record.get_changed_fields_dict.return_value = {}
        record.changed_by_username = "admin"
        record.change_time = datetime(2024, 1, 1)
        record.change_message = "test change"

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
            ):
                with patch(
                    "openviper.admin.api.views.get_change_history",
                    new_callable=AsyncMock,
                    return_value=[record],
                ):
                    response = await handler(_mock_request(), model_name="MyModel", obj_id=1)

        body = json.loads(response.body)
        assert len(body["history"]) == 1


# ---------------------------------------------------------------------------
# fk_search – full coverage (lines 1533-1597)
# ---------------------------------------------------------------------------


class TestFkSearch:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "fk_search")

        with patch("openviper.admin.api.views.check_admin_access", return_value=False):
            with pytest.raises(PermissionDenied):
                await handler(_mock_request(), app_label="a", model_name="X")

    @pytest.mark.asyncio
    async def test_model_found_in_registry(self):
        """Lines 1538-1540: model found via admin registry."""
        router = _make_router()
        handler = _get_handler(router, "fk_search")

        mock_instance = MagicMock()
        mock_instance.id = 1
        mock_instance.__str__ = lambda self: "Article #1"

        qs = _make_qs(items=[mock_instance])
        mock_model = MagicMock()
        mock_model._fields = {}
        mock_model.objects.all.return_value = qs

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_by_app_and_name",
                return_value=mock_model,
            ):
                response = await handler(
                    _mock_request(query_params={"limit": "10"}),
                    app_label="myapp",
                    model_name="Article",
                )

        body = json.loads(response.body)
        assert "items" in body

    @pytest.mark.asyncio
    async def test_model_not_in_registry_uses_importlib(self):
        """Lines 1543-1550: falls back to importlib import."""
        from openviper.admin.registry import NotRegistered

        router = _make_router()
        handler = _get_handler(router, "fk_search")

        mock_instance = MagicMock()
        mock_instance.id = 5
        mock_instance.__str__ = lambda self: "Item"

        qs = _make_qs(items=[mock_instance])
        mock_model = MagicMock()
        mock_model._fields = {}
        mock_model.objects.all.return_value = qs

        mock_module = MagicMock()
        mock_module.Article = mock_model

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_by_app_and_name",
                side_effect=NotRegistered("x"),
            ):
                with patch(
                    "openviper.admin.api.views.importlib.import_module",
                    return_value=mock_module,
                ):
                    response = await handler(
                        _mock_request(query_params={}),
                        app_label="myapp",
                        model_name="Article",
                    )

        body = json.loads(response.body)
        assert "items" in body

    @pytest.mark.asyncio
    async def test_model_found_by_scanning_all_models(self):
        """Lines 1552-1557: scans all registered models to find by name."""
        from openviper.admin.registry import NotRegistered

        router = _make_router()
        handler = _get_handler(router, "fk_search")

        mock_instance = MagicMock()
        mock_instance.id = 3

        qs = _make_qs(items=[mock_instance])
        mock_model = MagicMock()
        mock_model.__name__ = "Article"
        mock_model._fields = {}
        mock_model.objects.all.return_value = qs

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_by_app_and_name",
                side_effect=NotRegistered("x"),
            ):
                # Patch importlib module object in views namespace so import raises
                with patch("openviper.admin.api.views.importlib") as mock_importlib_mod:
                    mock_importlib_mod.import_module.side_effect = ImportError("no module")
                    with patch(
                        "openviper.admin.api.views.admin.get_all_models",
                        return_value=[(mock_model, MagicMock())],
                    ):
                        response = await handler(
                            _mock_request(query_params={}),
                            app_label="myapp",
                            model_name="Article",
                        )

        body = json.loads(response.body)
        assert "items" in body

    @pytest.mark.asyncio
    async def test_model_not_found_anywhere_raises_not_found(self):
        """Line 1559-1560: model not found anywhere raises NotFound."""
        from openviper.admin.registry import NotRegistered

        router = _make_router()
        handler = _get_handler(router, "fk_search")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_by_app_and_name",
                side_effect=NotRegistered("x"),
            ):
                with patch("openviper.admin.api.views.importlib") as mock_importlib_mod:
                    mock_importlib_mod.import_module.side_effect = ImportError("no module")
                    with patch(
                        "openviper.admin.api.views.admin.get_all_models",
                        return_value=[],
                    ):
                        with pytest.raises(NotFound):
                            await handler(
                                _mock_request(query_params={}),
                                app_label="myapp",
                                model_name="NonExistent",
                            )

    @pytest.mark.asyncio
    async def test_search_query_applied_to_text_fields(self):
        """Lines 1569-1581: q param triggers filter on text fields."""
        router = _make_router()
        handler = _get_handler(router, "fk_search")

        mock_instance = MagicMock()
        mock_instance.id = 1

        qs = _make_qs(items=[mock_instance])
        mock_model = MagicMock()

        name_field = MagicMock()
        name_field.__class__.__name__ = "CharField"
        mock_model._fields = {"name": name_field}
        mock_model.objects.all.return_value = qs

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_by_app_and_name",
                return_value=mock_model,
            ):
                await handler(
                    _mock_request(query_params={"q": "foo"}),
                    app_label="myapp",
                    model_name="Article",
                )

        qs.filter.assert_called_with(name__contains="foo")


# ---------------------------------------------------------------------------
# global_search (lines 1620-1674)
# ---------------------------------------------------------------------------


class TestGlobalSearch:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "global_search")

        with patch("openviper.admin.api.views.check_admin_access", return_value=False):
            with pytest.raises(PermissionDenied):
                await handler(_mock_request())

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_results(self):
        """Lines 1623-1625: empty q returns empty results immediately."""
        router = _make_router()
        handler = _get_handler(router, "global_search")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            response = await handler(_mock_request(query_params={"q": ""}))

        body = json.loads(response.body)
        assert body["results"] == []

    @pytest.mark.asyncio
    async def test_skips_models_without_permission(self):
        """Line 1633-1634: model without view permission is skipped."""
        router = _make_router()
        handler = _get_handler(router, "global_search")

        mock_model = MagicMock()
        mock_model.__name__ = "Secret"

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_all_models",
                return_value=[(mock_model, MagicMock())],
            ):
                with patch("openviper.admin.api.views.check_model_permission", return_value=False):
                    response = await handler(_mock_request(query_params={"q": "test"}))

        body = json.loads(response.body)
        assert body["results"] == []

    @pytest.mark.asyncio
    async def test_uses_admin_search_fields(self):
        """Lines 1637-1638, 1650-1657: uses model_admin.get_search_fields."""
        router = _make_router()
        handler = _get_handler(router, "global_search")

        mock_instance = MagicMock()
        mock_instance.id = 1
        mock_instance.__str__ = lambda self: "Article 1"

        qs = _make_qs(items=[mock_instance])
        mock_model = MagicMock()
        mock_model.__name__ = "Article"
        mock_model._fields = {}
        mock_model.objects.all.return_value = qs

        mock_model_admin = MagicMock()
        mock_model_admin.get_search_fields.return_value = ["title"]
        mock_model_admin._get_app_label = MagicMock(return_value="myapp")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_all_models",
                return_value=[(mock_model, mock_model_admin)],
            ):
                with patch("openviper.admin.api.views.check_model_permission", return_value=True):
                    with patch(
                        "openviper.admin.api.views.admin._get_app_label", return_value="myapp"
                    ):
                        response = await handler(_mock_request(query_params={"q": "Article"}))

        body = json.loads(response.body)
        assert "results" in body

    @pytest.mark.asyncio
    async def test_falls_back_to_common_field_names(self):
        """Lines 1639-1647: no search_fields, falls back to name/title/etc."""
        router = _make_router()
        handler = _get_handler(router, "global_search")

        mock_instance = MagicMock()
        mock_instance.id = 2

        qs = _make_qs(items=[mock_instance])
        mock_model = MagicMock()
        mock_model.__name__ = "Article"
        mock_model._fields = {"title": MagicMock()}
        mock_model.objects.all.return_value = qs

        mock_model_admin = MagicMock()
        mock_model_admin.get_search_fields.return_value = []

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_all_models",
                return_value=[(mock_model, mock_model_admin)],
            ):
                with patch("openviper.admin.api.views.check_model_permission", return_value=True):
                    with patch("openviper.admin.api.views.admin._get_app_label", return_value="a"):
                        response = await handler(_mock_request(query_params={"q": "test"}))

        body = json.loads(response.body)
        assert "results" in body

    @pytest.mark.asyncio
    async def test_skips_model_with_no_usable_search_fields(self):
        """Line 1646-1647: model without usable fields is skipped entirely."""
        router = _make_router()
        handler = _get_handler(router, "global_search")

        mock_model = MagicMock()
        mock_model.__name__ = "WeirdModel"
        mock_model._fields = {"count": MagicMock()}  # no name/title/etc.

        mock_model_admin = MagicMock()
        mock_model_admin.get_search_fields.return_value = []

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_all_models",
                return_value=[(mock_model, mock_model_admin)],
            ):
                with patch("openviper.admin.api.views.check_model_permission", return_value=True):
                    response = await handler(_mock_request(query_params={"q": "test"}))

        body = json.loads(response.body)
        assert body["results"] == []


# ---------------------------------------------------------------------------
# _serialize_instance_with_children – non-primitive child field str() (line 121)
# ---------------------------------------------------------------------------


class TestSerializeChildNonPrimitive:
    @pytest.mark.asyncio
    async def test_child_non_primitive_converted_to_str(self):
        """Line 121: non-primitive child field value is str()-converted."""

        class ObjVal:
            def __str__(self):
                return "child_str"

        child_record = MagicMock()
        child_record.id = 7
        child_record.data = ObjVal()

        child_qs = MagicMock()
        child_qs.filter.return_value = child_qs
        child_qs.all = AsyncMock(return_value=[child_record])

        child_model = MagicMock()
        child_model.__name__ = "Tag"
        child_model._fields = {}
        child_model.objects.filter.return_value = child_qs

        inline = MagicMock()
        inline.model = child_model
        inline.fk_name = "parent_id"
        inline.extra_filters = {}
        inline.fields = ["data"]

        inline_class = MagicMock(return_value=inline)
        model_admin = MagicMock()
        model_admin.child_tables = [inline_class]
        model_admin.inlines = []

        model_class = MagicMock()
        model_class._fields = {}
        model_class.__name__ = "Parent"

        instance = MagicMock()
        instance.id = 1

        result = await _serialize_instance_with_children(
            _mock_request(), model_admin, model_class, instance
        )

        assert result["tag_set"][0]["data"] == "child_str"


# ---------------------------------------------------------------------------
# create_instance_by_app – NotRegistered path (lines 584-585)
# ---------------------------------------------------------------------------


class TestCreateInstanceByAppNotRegistered:
    @pytest.mark.asyncio
    async def test_not_registered_raises_not_found(self):
        from openviper.admin.registry import NotRegistered

        router = _make_router()
        handler = _get_handler(router, "create_instance_by_app")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                side_effect=NotRegistered("x"),
            ):
                with pytest.raises(NotFound):
                    await handler(_mock_request(), app_label="a", model_name="X")


# ---------------------------------------------------------------------------
# create_instance_by_app – child sync path (lines 614-644)
# ---------------------------------------------------------------------------


class TestCreateInstanceByAppChildSync:
    @pytest.mark.asyncio
    async def test_child_rows_saved_during_create(self):
        """Lines 614-644: child rows provided in request body are saved."""
        router = _make_router()
        handler = _get_handler(router, "create_instance_by_app")

        child_inst = MagicMock()
        child_inst.save = AsyncMock()

        child_model = MagicMock()
        child_model.__name__ = "Comment"
        child_model._fields = {}
        child_model.return_value = child_inst

        inline = MagicMock()
        inline.model = child_model
        inline.fk_name = "article_id"
        inline.extra_filters = {}

        inline_class = MagicMock(return_value=inline)

        mock_instance = MagicMock()
        mock_instance.id = 5
        mock_instance.save = AsyncMock()

        mock_model_admin = MagicMock()
        mock_model_admin.has_add_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = []
        mock_model_admin.child_tables = [inline_class]
        mock_model_admin.inlines = []

        mock_model = MagicMock()
        mock_model._fields = {}
        mock_model.return_value = mock_instance

        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.get_engine",
                        new_callable=AsyncMock,
                        return_value=mock_engine,
                    ):
                        with patch(
                            "openviper.admin.api.views._serialize_instance_with_children",
                            new_callable=AsyncMock,
                            return_value={"id": 5},
                        ):
                            response = await handler(
                                _mock_request(json_data={"comment_set": [{"text": "hello"}]}),
                                app_label="a",
                                model_name="Article",
                            )

        assert response.status_code == 201
        child_inst.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_child_sync_with_extra_filters(self):
        """Lines 641-643: extra_filters applied to new child rows."""
        router = _make_router()
        handler = _get_handler(router, "create_instance_by_app")

        child_inst = MagicMock()
        child_inst.save = AsyncMock()

        child_model = MagicMock()
        child_model.__name__ = "Tag"
        child_model._fields = {}
        child_model.return_value = child_inst

        inline = MagicMock()
        inline.model = child_model
        inline.fk_name = "parent_id"
        inline.extra_filters = {"active": True}

        inline_class = MagicMock(return_value=inline)

        mock_instance = MagicMock()
        mock_instance.id = 3
        mock_instance.save = AsyncMock()

        mock_model_admin = MagicMock()
        mock_model_admin.has_add_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = []
        mock_model_admin.child_tables = [inline_class]
        mock_model_admin.inlines = []

        mock_model = MagicMock()
        mock_model._fields = {}
        mock_model.return_value = mock_instance

        mock_engine = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.get_engine",
                        new_callable=AsyncMock,
                        return_value=mock_engine,
                    ):
                        with patch(
                            "openviper.admin.api.views._serialize_instance_with_children",
                            new_callable=AsyncMock,
                            return_value={"id": 3},
                        ):
                            response = await handler(
                                _mock_request(json_data={"tag_set": [{"name": "x"}]}),
                                app_label="a",
                                model_name="Article",
                            )

        assert response.status_code == 201


# ---------------------------------------------------------------------------
# create_instance_by_app – IntegrityError path (lines 647-649)
# ---------------------------------------------------------------------------


class TestCreateInstanceByAppIntegrityError:
    @pytest.mark.asyncio
    async def test_integrity_error_returns_422(self):
        """Lines 647-649: IntegrityError during save returns 422."""
        import sqlalchemy.exc

        router = _make_router()
        handler = _get_handler(router, "create_instance_by_app")

        mock_instance = MagicMock()
        exc_orig = Exception("unique constraint")
        integrity_exc = sqlalchemy.exc.IntegrityError("stmt", {}, exc_orig)
        mock_instance.save = AsyncMock(side_effect=integrity_exc)

        mock_model_admin = MagicMock()
        mock_model_admin.has_add_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = []
        mock_model_admin.child_tables = []
        mock_model_admin.inlines = []

        mock_model = MagicMock()
        mock_model._fields = {}
        mock_model.return_value = mock_instance

        mock_engine = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.get_engine",
                        new_callable=AsyncMock,
                        return_value=mock_engine,
                    ):
                        response = await handler(
                            _mock_request(json_data={"title": "X"}),
                            app_label="a",
                            model_name="Article",
                        )

        assert response.status_code == 422
        body = json.loads(response.body)
        assert "errors" in body


# ---------------------------------------------------------------------------
# get_instance_by_app – NotRegistered path (lines 678-679)
# ---------------------------------------------------------------------------


class TestGetInstanceByAppNotRegistered:
    @pytest.mark.asyncio
    async def test_not_registered_raises_not_found(self):
        from openviper.admin.registry import NotRegistered

        router = _make_router()
        handler = _get_handler(router, "get_instance_by_app")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                side_effect=NotRegistered("x"),
            ):
                with pytest.raises(NotFound):
                    await handler(_mock_request(), app_label="a", model_name="X", obj_id=1)


# ---------------------------------------------------------------------------
# update_instance_by_app – with non-empty fields (lines 732, 740, 742-744)
# ---------------------------------------------------------------------------


class TestUpdateInstanceByAppWithFields:
    @pytest.mark.asyncio
    async def test_field_coercion_in_update(self):
        """Lines 732, 740, 742-744: field coercion applied for known fields."""
        router = _make_router()
        handler = _get_handler(router, "update_instance_by_app")

        mock_instance = MagicMock()
        mock_instance.id = 1
        mock_instance.title = "Old"
        mock_instance.save = AsyncMock()

        fake_field = MagicMock()

        mock_model_admin = MagicMock()
        mock_model_admin.has_change_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = []
        mock_model_admin.child_tables = []
        mock_model_admin.inlines = []

        mock_model = MagicMock()
        mock_model._fields = {"title": fake_field}
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        mock_engine = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.get_engine",
                        new_callable=AsyncMock,
                        return_value=mock_engine,
                    ):
                        with patch(
                            "openviper.admin.api.views.coerce_field_value",
                            return_value="New",
                        ) as mock_coerce:
                            with patch(
                                "openviper.admin.api.views._serialize_instance_with_children",
                                new_callable=AsyncMock,
                                return_value={"id": 1, "title": "New"},
                            ):
                                with patch(
                                    "openviper.admin.api.views.log_change",
                                    new_callable=AsyncMock,
                                ):
                                    with patch(
                                        "openviper.admin.api.views.compute_changes",
                                        return_value={"title": ("Old", "New")},
                                    ):
                                        response = await handler(
                                            _mock_request(json_data={"title": "New"}),
                                            app_label="a",
                                            model_name="Article",
                                            obj_id=1,
                                        )

        assert response.status_code == 200
        mock_coerce.assert_called_once_with(fake_field, "New")

    @pytest.mark.asyncio
    async def test_readonly_field_skipped_in_update(self):
        """Line 740: readonly fields skipped during update field coercion."""
        router = _make_router()
        handler = _get_handler(router, "update_instance_by_app")

        mock_instance = MagicMock()
        mock_instance.id = 1
        mock_instance.title = "Old"
        mock_instance.save = AsyncMock()

        mock_model_admin = MagicMock()
        mock_model_admin.has_change_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = ["title"]
        mock_model_admin.child_tables = []
        mock_model_admin.inlines = []

        mock_model = MagicMock()
        mock_model._fields = {"title": MagicMock()}
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        mock_engine = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.get_engine",
                        new_callable=AsyncMock,
                        return_value=mock_engine,
                    ):
                        with patch(
                            "openviper.admin.api.views._serialize_instance_with_children",
                            new_callable=AsyncMock,
                            return_value={"id": 1},
                        ):
                            with patch(
                                "openviper.admin.api.views.log_change",
                                new_callable=AsyncMock,
                            ):
                                with patch(
                                    "openviper.admin.api.views.compute_changes",
                                    return_value={},
                                ):
                                    response = await handler(
                                        _mock_request(json_data={"title": "New"}),
                                        app_label="a",
                                        model_name="Article",
                                        obj_id=1,
                                    )

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# update_instance_by_app – child sync (lines 757-814)
# ---------------------------------------------------------------------------


class TestUpdateInstanceByAppChildSync:
    @pytest.mark.asyncio
    async def test_child_sync_creates_and_deletes(self):
        """Lines 757-814: child sync creates new rows and deletes missing rows."""
        router = _make_router()
        handler = _get_handler(router, "update_instance_by_app")

        existing_child = MagicMock()
        existing_child.id = 99
        existing_child.save = AsyncMock()
        existing_child.delete = AsyncMock()

        child_new_inst = MagicMock()
        child_new_inst.id = 100
        child_new_inst.save = AsyncMock()

        child_qs = MagicMock()
        child_qs.filter.return_value = child_qs
        child_qs.all = AsyncMock(return_value=[existing_child])

        child_model = MagicMock()
        child_model.__name__ = "Comment"
        child_model._fields = {}
        child_model.objects.filter.return_value = child_qs
        child_model.return_value = child_new_inst

        inline = MagicMock()
        inline.model = child_model
        inline.fk_name = "article_id"
        inline.extra_filters = {}

        inline_class = MagicMock(return_value=inline)

        mock_instance = MagicMock()
        mock_instance.id = 1
        mock_instance.save = AsyncMock()

        mock_model_admin = MagicMock()
        mock_model_admin.has_change_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = []
        mock_model_admin.child_tables = [inline_class]
        mock_model_admin.inlines = []

        mock_model = MagicMock()
        mock_model._fields = {}
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        mock_engine = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.get_engine",
                        new_callable=AsyncMock,
                        return_value=mock_engine,
                    ):
                        with patch(
                            "openviper.admin.api.views._serialize_instance_with_children",
                            new_callable=AsyncMock,
                            return_value={"id": 1},
                        ):
                            with patch(
                                "openviper.admin.api.views.log_change",
                                new_callable=AsyncMock,
                            ):
                                with patch(
                                    "openviper.admin.api.views.compute_changes",
                                    return_value={},
                                ):
                                    response = await handler(
                                        _mock_request(json_data={"comment_set": [{"text": "new"}]}),
                                        app_label="a",
                                        model_name="Article",
                                        obj_id=1,
                                    )

        assert response.status_code == 200
        child_new_inst.save.assert_awaited_once()
        existing_child.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_child_sync_updates_existing(self):
        """Lines 788-795: existing child matched by id is updated and kept."""
        router = _make_router()
        handler = _get_handler(router, "update_instance_by_app")

        existing_child = MagicMock()
        existing_child.id = 10
        existing_child.save = AsyncMock()
        existing_child.delete = AsyncMock()

        child_qs = MagicMock()
        child_qs.filter.return_value = child_qs
        child_qs.all = AsyncMock(return_value=[existing_child])

        child_model = MagicMock()
        child_model.__name__ = "Tag"
        child_model._fields = {}
        child_model.objects.filter.return_value = child_qs

        inline = MagicMock()
        inline.model = child_model
        inline.fk_name = "parent_id"
        inline.extra_filters = {}

        inline_class = MagicMock(return_value=inline)

        mock_instance = MagicMock()
        mock_instance.id = 2
        mock_instance.save = AsyncMock()

        mock_model_admin = MagicMock()
        mock_model_admin.has_change_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = []
        mock_model_admin.child_tables = [inline_class]
        mock_model_admin.inlines = []

        mock_model = MagicMock()
        mock_model._fields = {}
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        mock_engine = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.get_engine",
                        new_callable=AsyncMock,
                        return_value=mock_engine,
                    ):
                        with patch(
                            "openviper.admin.api.views._serialize_instance_with_children",
                            new_callable=AsyncMock,
                            return_value={"id": 2},
                        ):
                            with patch(
                                "openviper.admin.api.views.log_change",
                                new_callable=AsyncMock,
                            ):
                                with patch(
                                    "openviper.admin.api.views.compute_changes",
                                    return_value={},
                                ):
                                    response = await handler(
                                        _mock_request(
                                            json_data={"tag_set": [{"id": 10, "name": "updated"}]}
                                        ),
                                        app_label="a",
                                        model_name="Article",
                                        obj_id=2,
                                    )

        assert response.status_code == 200
        existing_child.save.assert_awaited_once()
        existing_child.delete.assert_not_called()


# ---------------------------------------------------------------------------
# update_instance_by_app – IntegrityError path (lines 818-820)
# ---------------------------------------------------------------------------


class TestUpdateInstanceByAppIntegrityError:
    @pytest.mark.asyncio
    async def test_integrity_error_returns_422(self):
        """Lines 818-820: IntegrityError during update save returns 422."""
        import sqlalchemy.exc

        router = _make_router()
        handler = _get_handler(router, "update_instance_by_app")

        mock_instance = MagicMock()
        mock_instance.id = 1
        exc_orig = Exception("unique")
        integrity_exc = sqlalchemy.exc.IntegrityError("stmt", {}, exc_orig)
        mock_instance.save = AsyncMock(side_effect=integrity_exc)

        mock_model_admin = MagicMock()
        mock_model_admin.has_change_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = []
        mock_model_admin.child_tables = []
        mock_model_admin.inlines = []

        mock_model = MagicMock()
        mock_model._fields = {}
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        mock_engine = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.get_engine",
                        new_callable=AsyncMock,
                        return_value=mock_engine,
                    ):
                        response = await handler(
                            _mock_request(json_data={"title": "x"}),
                            app_label="a",
                            model_name="Article",
                            obj_id=1,
                        )

        assert response.status_code == 422
        body = json.loads(response.body)
        assert "errors" in body


# ---------------------------------------------------------------------------
# create_instance (legacy) – NotRegistered path (lines 1125-1126)
# ---------------------------------------------------------------------------


class TestCreateInstanceNotRegistered:
    @pytest.mark.asyncio
    async def test_not_registered_raises_not_found(self):
        from openviper.admin.registry import NotRegistered

        router = _make_router()
        handler = _get_handler(router, "create_instance")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                side_effect=NotRegistered("x"),
            ):
                with pytest.raises(NotFound):
                    await handler(_mock_request(), model_name="X")


# ---------------------------------------------------------------------------
# get_instance (legacy) – no access + NotRegistered + serialization
# (lines 1174, 1179-1198)
# ---------------------------------------------------------------------------


class TestGetInstanceLegacyExtra:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        """Line 1174: no admin access raises PermissionDenied."""
        router = _make_router()
        handler = _get_handler(router, "get_instance")

        with patch("openviper.admin.api.views.check_admin_access", return_value=False):
            with pytest.raises(PermissionDenied):
                await handler(_mock_request(), model_name="X", obj_id=1)

    @pytest.mark.asyncio
    async def test_not_registered_raises_not_found(self):
        """Lines 1179-1180: NotRegistered raises NotFound."""
        from openviper.admin.registry import NotRegistered

        router = _make_router()
        handler = _get_handler(router, "get_instance")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                side_effect=NotRegistered("x"),
            ):
                with pytest.raises(NotFound):
                    await handler(_mock_request(), model_name="X", obj_id=1)

    @pytest.mark.asyncio
    async def test_field_serialization_in_response(self):
        """Lines 1193-1198: instance fields are serialized in response."""
        from datetime import datetime

        router = _make_router()
        handler = _get_handler(router, "get_instance")

        dt = datetime(2024, 6, 1)
        mock_instance = MagicMock()
        mock_instance.id = 10
        mock_instance.ts = dt

        mock_model_admin = MagicMock()
        mock_model_admin.has_view_permission.return_value = True
        mock_model_admin.get_model_info.return_value = {}
        mock_model_admin.get_readonly_fields.return_value = []
        mock_model_admin.get_fieldsets.return_value = []

        mock_model = MagicMock()
        mock_model._fields = {"ts": MagicMock()}
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name",
                    return_value=mock_model,
                ):
                    response = await handler(_mock_request(), model_name="Article", obj_id=10)

        body = json.loads(response.body)
        assert body["instance"]["ts"] == dt.isoformat()


# ---------------------------------------------------------------------------
# update_instance (legacy) – NotRegistered + field ops + response
# (lines 1221-1275)
# ---------------------------------------------------------------------------


class TestUpdateInstanceLegacyExtra:
    @pytest.mark.asyncio
    async def test_not_registered_raises_not_found(self):
        """Lines 1221-1222: NotRegistered raises NotFound."""
        from openviper.admin.registry import NotRegistered

        router = _make_router()
        handler = _get_handler(router, "update_instance")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                side_effect=NotRegistered("x"),
            ):
                with pytest.raises(NotFound):
                    await handler(_mock_request(), model_name="X", obj_id=1)

    @pytest.mark.asyncio
    async def test_field_ops_and_response_serialization(self):
        """Lines 1237, 1247-1249, 1272-1275: field coercion + response serialization."""
        from datetime import datetime

        router = _make_router()
        handler = _get_handler(router, "update_instance")

        dt = datetime(2024, 8, 15)
        mock_instance = MagicMock()
        mock_instance.id = 5
        mock_instance.ts = dt
        mock_instance.save = AsyncMock()

        fake_field = MagicMock()

        mock_model_admin = MagicMock()
        mock_model_admin.has_change_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = []

        mock_model = MagicMock()
        mock_model._fields = {"ts": fake_field}
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.coerce_field_value",
                        return_value=dt,
                    ) as mock_coerce:
                        with patch("openviper.admin.api.views.log_change", new_callable=AsyncMock):
                            with patch(
                                "openviper.admin.api.views.compute_changes",
                                return_value={"ts": (None, dt)},
                            ):
                                response = await handler(
                                    _mock_request(json_data={"ts": dt.isoformat()}),
                                    model_name="Article",
                                    obj_id=5,
                                )

        assert response.status_code == 200
        mock_coerce.assert_called_once_with(fake_field, dt.isoformat())
        body = json.loads(response.body)
        assert body["ts"] == dt.isoformat()

    @pytest.mark.asyncio
    async def test_readonly_field_skipped_in_legacy_update(self):
        """Line 1245: readonly field skipped in legacy update."""
        router = _make_router()
        handler = _get_handler(router, "update_instance")

        mock_instance = MagicMock()
        mock_instance.id = 3
        mock_instance.count = 0
        mock_instance.save = AsyncMock()

        mock_model_admin = MagicMock()
        mock_model_admin.has_change_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = ["count"]

        mock_model = MagicMock()
        mock_model._fields = {"count": MagicMock()}
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name",
                    return_value=mock_model,
                ):
                    with patch("openviper.admin.api.views.log_change", new_callable=AsyncMock):
                        with patch("openviper.admin.api.views.compute_changes", return_value={}):
                            response = await handler(
                                _mock_request(json_data={"count": 99}),
                                model_name="Article",
                                obj_id=3,
                            )

        assert response.status_code == 200
        body = json.loads(response.body)
        assert body["count"] == 0


# ---------------------------------------------------------------------------
# delete_instance (legacy) – no admin access (line 1283)
# ---------------------------------------------------------------------------


class TestDeleteInstanceNoAccess:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        """Line 1283: no admin access raises PermissionDenied in delete_instance."""
        router = _make_router()
        handler = _get_handler(router, "delete_instance")

        with patch("openviper.admin.api.views.check_admin_access", return_value=False):
            with pytest.raises(PermissionDenied):
                await handler(_mock_request(), model_name="X", obj_id=1)


# ---------------------------------------------------------------------------
# get_filter_options – field with choices (line 1438)
# ---------------------------------------------------------------------------


class TestGetFilterOptionsChoices:
    @pytest.mark.asyncio
    async def test_field_with_choices_returns_them(self):
        """Line 1438: field with choices returns serialized choices list."""
        router = _make_router()
        handler = _get_handler(router, "get_filter_options")

        mock_field = MagicMock()
        mock_field.__class__.__name__ = "CharField"
        mock_field.choices = [("active", "Active"), ("inactive", "Inactive")]

        mock_model_admin = MagicMock()
        mock_model_admin.get_list_filter.return_value = ["status"]
        mock_model = MagicMock()
        mock_model._fields = {"status": mock_field}

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        response = await handler(_mock_request(), model_name="Article")

        body = json.loads(response.body)
        choices = body["filters"][0]["choices"]
        assert len(choices) == 2
        assert choices[0] == {"value": "active", "label": "Active"}
        assert choices[1] == {"value": "inactive", "label": "Inactive"}


# ---------------------------------------------------------------------------
# global_search – cap at 50 results (lines 1694, 1697)
# ---------------------------------------------------------------------------


class TestGlobalSearchCap:
    @pytest.mark.asyncio
    async def test_results_capped_at_50(self):
        """Lines 1694, 1697: results are capped at 50 across all models."""
        router = _make_router()
        handler = _get_handler(router, "global_search")

        # 11 models × 5 instances each → 55 total, capped at 50
        all_models = []
        for i in range(11):
            instances = []
            for j in range(5):
                inst = MagicMock()
                inst.id = i * 10 + j
                inst.__str__ = lambda self: "item"
                instances.append(inst)

            qs = _make_qs(items=instances)
            model = MagicMock()
            model.__name__ = f"Model{i}"
            model._fields = {"title": MagicMock()}
            model.objects.all.return_value = qs

            model_admin = MagicMock()
            model_admin.get_search_fields.return_value = ["title"]
            model_admin._get_app_label = MagicMock(return_value="app")

            all_models.append((model, model_admin))

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_all_models",
                return_value=all_models,
            ):
                with patch("openviper.admin.api.views.check_model_permission", return_value=True):
                    with patch(
                        "openviper.admin.api.views.admin._get_app_label", return_value="app"
                    ):
                        response = await handler(_mock_request(query_params={"q": "item"}))

        body = json.loads(response.body)
        assert len(body["results"]) == 50


# ---------------------------------------------------------------------------
# create_instance_by_app – FK auto-discovery in child sync (lines 619-629)
# ---------------------------------------------------------------------------


class TestCreateInstanceByAppChildFKAutoDiscover:
    def _base_setup(self):
        mock_instance = MagicMock()
        mock_instance.id = 7
        mock_instance.save = AsyncMock()

        mock_model_admin = MagicMock()
        mock_model_admin.has_add_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = []
        mock_model_admin.inlines = []

        mock_model = MagicMock()
        mock_model._fields = {}
        mock_model.return_value = mock_instance

        mock_engine = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

        return mock_instance, mock_model_admin, mock_model, mock_engine

    @pytest.mark.asyncio
    async def test_fk_name_auto_discovered_during_create(self):
        """Lines 619-626: when fk_name is empty, FK field is auto-discovered."""
        router = _make_router()
        handler = _get_handler(router, "create_instance_by_app")

        mock_instance, mock_model_admin, mock_model, mock_engine = self._base_setup()

        child_inst = MagicMock()
        child_inst.save = AsyncMock()

        model_class_ref = mock_model  # will be compared in resolve_target

        fk_field = MagicMock()
        fk_field.__class__.__name__ = "ForeignKey"
        fk_field.resolve_target.return_value = model_class_ref

        child_model = MagicMock()
        child_model.__name__ = "Comment"
        child_model._fields = {"article_id": fk_field}
        child_model.return_value = child_inst

        inline = MagicMock()
        inline.model = child_model
        inline.fk_name = ""  # empty → auto-discover
        inline.extra_filters = {}

        inline_class = MagicMock(return_value=inline)
        mock_model_admin.child_tables = [inline_class]

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=model_class_ref,
                ):
                    with patch(
                        "openviper.admin.api.views.get_engine",
                        new_callable=AsyncMock,
                        return_value=mock_engine,
                    ):
                        with patch(
                            "openviper.admin.api.views._serialize_instance_with_children",
                            new_callable=AsyncMock,
                            return_value={"id": 7},
                        ):
                            response = await handler(
                                _mock_request(json_data={"comment_set": [{"text": "hi"}]}),
                                app_label="a",
                                model_name="Article",
                            )

        assert response.status_code == 201
        child_inst.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fk_name_not_found_skips_inline(self):
        """Line 629: when fk_name cannot be auto-discovered, inline is skipped."""
        router = _make_router()
        handler = _get_handler(router, "create_instance_by_app")

        mock_instance, mock_model_admin, mock_model, mock_engine = self._base_setup()

        child_inst = MagicMock()
        child_inst.save = AsyncMock()

        child_model = MagicMock()
        child_model.__name__ = "Orphan"
        child_model._fields = {}  # no FK fields → can't discover fk_name
        child_model.return_value = child_inst

        inline = MagicMock()
        inline.model = child_model
        inline.fk_name = ""  # empty AND no FK in child_fields
        inline.extra_filters = {}

        inline_class = MagicMock(return_value=inline)
        mock_model_admin.child_tables = [inline_class]

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.get_engine",
                        new_callable=AsyncMock,
                        return_value=mock_engine,
                    ):
                        with patch(
                            "openviper.admin.api.views._serialize_instance_with_children",
                            new_callable=AsyncMock,
                            return_value={"id": 7},
                        ):
                            response = await handler(
                                _mock_request(json_data={"orphan_set": [{"x": 1}]}),
                                app_label="a",
                                model_name="Article",
                            )

        assert response.status_code == 201
        child_inst.save.assert_not_called()


# ---------------------------------------------------------------------------
# update_instance_by_app – FK auto-discovery in child sync (lines 762-772)
# ---------------------------------------------------------------------------


class TestUpdateInstanceByAppChildFKAutoDiscover:
    def _base_setup(self):
        mock_instance = MagicMock()
        mock_instance.id = 3
        mock_instance.save = AsyncMock()

        mock_model_admin = MagicMock()
        mock_model_admin.has_change_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = []
        mock_model_admin.inlines = []

        mock_model = MagicMock()
        mock_model._fields = {}
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        mock_engine = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

        return mock_instance, mock_model_admin, mock_model, mock_engine

    @pytest.mark.asyncio
    async def test_fk_name_auto_discovered_during_update(self):
        """Lines 762-769: when fk_name is empty, FK auto-discovered in update path."""
        router = _make_router()
        handler = _get_handler(router, "update_instance_by_app")

        mock_instance, mock_model_admin, mock_model, mock_engine = self._base_setup()

        child_inst = MagicMock()
        child_inst.save = AsyncMock()
        child_inst.delete = AsyncMock()

        child_qs = MagicMock()
        child_qs.filter.return_value = child_qs
        child_qs.all = AsyncMock(return_value=[])

        fk_field = MagicMock()
        fk_field.__class__.__name__ = "ForeignKey"
        fk_field.resolve_target.return_value = mock_model

        child_model = MagicMock()
        child_model.__name__ = "Tag"
        child_model._fields = {"parent_fk": fk_field}
        child_model.objects.filter.return_value = child_qs
        child_model.return_value = child_inst

        inline = MagicMock()
        inline.model = child_model
        inline.fk_name = ""  # empty → auto-discover
        inline.extra_filters = {}

        inline_class = MagicMock(return_value=inline)
        mock_model_admin.child_tables = [inline_class]

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.get_engine",
                        new_callable=AsyncMock,
                        return_value=mock_engine,
                    ):
                        with patch(
                            "openviper.admin.api.views._serialize_instance_with_children",
                            new_callable=AsyncMock,
                            return_value={"id": 3},
                        ):
                            with patch(
                                "openviper.admin.api.views.log_change",
                                new_callable=AsyncMock,
                            ):
                                with patch(
                                    "openviper.admin.api.views.compute_changes",
                                    return_value={},
                                ):
                                    response = await handler(
                                        _mock_request(json_data={"tag_set": [{"name": "new"}]}),
                                        app_label="a",
                                        model_name="Article",
                                        obj_id=3,
                                    )

        assert response.status_code == 200
        child_inst.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fk_name_not_found_skips_inline_in_update(self):
        """Line 772: when fk_name cannot be auto-discovered, inline skipped in update."""
        router = _make_router()
        handler = _get_handler(router, "update_instance_by_app")

        mock_instance, mock_model_admin, mock_model, mock_engine = self._base_setup()

        child_inst = MagicMock()
        child_inst.save = AsyncMock()
        child_inst.delete = AsyncMock()

        child_model = MagicMock()
        child_model.__name__ = "Orphan"
        child_model._fields = {}  # no FK fields

        inline = MagicMock()
        inline.model = child_model
        inline.fk_name = ""  # empty AND no FK in child model
        inline.extra_filters = {}

        inline_class = MagicMock(return_value=inline)
        mock_model_admin.child_tables = [inline_class]

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.get_engine",
                        new_callable=AsyncMock,
                        return_value=mock_engine,
                    ):
                        with patch(
                            "openviper.admin.api.views._serialize_instance_with_children",
                            new_callable=AsyncMock,
                            return_value={"id": 3},
                        ):
                            with patch(
                                "openviper.admin.api.views.log_change",
                                new_callable=AsyncMock,
                            ):
                                with patch(
                                    "openviper.admin.api.views.compute_changes",
                                    return_value={},
                                ):
                                    response = await handler(
                                        _mock_request(json_data={"orphan_set": [{"x": 1}]}),
                                        app_label="a",
                                        model_name="Article",
                                        obj_id=3,
                                    )

        assert response.status_code == 200
        child_inst.save.assert_not_called()


# ---------------------------------------------------------------------------
# update_instance_by_app – extra_filters in child sync (lines 780, 805-806)
# ---------------------------------------------------------------------------


class TestUpdateInstanceByAppChildExtraFilters:
    @pytest.mark.asyncio
    async def test_extra_filters_applied_to_existing_records_query(self):
        """Line 780: extra_filters merged into child records query."""
        router = _make_router()
        handler = _get_handler(router, "update_instance_by_app")

        existing_child = MagicMock()
        existing_child.id = 20
        existing_child.save = AsyncMock()
        existing_child.delete = AsyncMock()

        child_qs = MagicMock()
        child_qs.filter.return_value = child_qs
        child_qs.all = AsyncMock(return_value=[existing_child])

        child_model = MagicMock()
        child_model.__name__ = "Item"
        child_model._fields = {}
        child_model.objects.filter.return_value = child_qs

        inline = MagicMock()
        inline.model = child_model
        inline.fk_name = "parent_id"
        inline.extra_filters = {"active": True}  # truthy → hits line 780

        inline_class = MagicMock(return_value=inline)

        mock_instance = MagicMock()
        mock_instance.id = 5
        mock_instance.save = AsyncMock()

        mock_model_admin = MagicMock()
        mock_model_admin.has_change_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = []
        mock_model_admin.child_tables = [inline_class]
        mock_model_admin.inlines = []

        mock_model = MagicMock()
        mock_model._fields = {}
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        mock_engine = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.get_engine",
                        new_callable=AsyncMock,
                        return_value=mock_engine,
                    ):
                        with patch(
                            "openviper.admin.api.views._serialize_instance_with_children",
                            new_callable=AsyncMock,
                            return_value={"id": 5},
                        ):
                            with patch(
                                "openviper.admin.api.views.log_change",
                                new_callable=AsyncMock,
                            ):
                                with patch(
                                    "openviper.admin.api.views.compute_changes",
                                    return_value={},
                                ):
                                    response = await handler(
                                        _mock_request(json_data={"item_set": []}),
                                        app_label="a",
                                        model_name="Article",
                                        obj_id=5,
                                    )

        assert response.status_code == 200
        # filter called with merged keys including extra_filters
        call_kwargs = child_model.objects.filter.call_args[1]
        assert call_kwargs.get("active") is True
        assert call_kwargs.get("parent_id") == 5

    @pytest.mark.asyncio
    async def test_extra_filters_applied_to_new_child_in_update(self):
        """Lines 805-806: extra_filters set on new child rows during update sync."""
        router = _make_router()
        handler = _get_handler(router, "update_instance_by_app")

        child_new_inst = MagicMock()
        child_new_inst.id = None
        child_new_inst.save = AsyncMock()

        child_qs = MagicMock()
        child_qs.filter.return_value = child_qs
        child_qs.all = AsyncMock(return_value=[])  # no existing records

        child_model = MagicMock()
        child_model.__name__ = "Tag"
        child_model._fields = {}
        child_model.objects.filter.return_value = child_qs
        child_model.return_value = child_new_inst

        inline = MagicMock()
        inline.model = child_model
        inline.fk_name = "article_id"
        inline.extra_filters = {"status": "active"}  # truthy → hits lines 805-806

        inline_class = MagicMock(return_value=inline)

        mock_instance = MagicMock()
        mock_instance.id = 8
        mock_instance.save = AsyncMock()

        mock_model_admin = MagicMock()
        mock_model_admin.has_change_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = []
        mock_model_admin.child_tables = [inline_class]
        mock_model_admin.inlines = []

        mock_model = MagicMock()
        mock_model._fields = {}
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        mock_engine = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.get_engine",
                        new_callable=AsyncMock,
                        return_value=mock_engine,
                    ):
                        with patch(
                            "openviper.admin.api.views._serialize_instance_with_children",
                            new_callable=AsyncMock,
                            return_value={"id": 8},
                        ):
                            with patch(
                                "openviper.admin.api.views.log_change",
                                new_callable=AsyncMock,
                            ):
                                with patch(
                                    "openviper.admin.api.views.compute_changes",
                                    return_value={},
                                ):
                                    response = await handler(
                                        _mock_request(json_data={"tag_set": [{"name": "new"}]}),
                                        app_label="a",
                                        model_name="Article",
                                        obj_id=8,
                                    )

        assert response.status_code == 200
        child_new_inst.save.assert_awaited_once()
        # extra_filter value was set on the new child instance
        assert child_new_inst.status == "active"


# ---------------------------------------------------------------------------
# create_instance (legacy) – readonly field skipped (line 1140)
# ---------------------------------------------------------------------------


class TestCreateInstanceReadonlySkipped:
    @pytest.mark.asyncio
    async def test_readonly_field_skipped_in_legacy_create(self):
        """Line 1140: readonly fields skipped in legacy create_instance."""
        router = _make_router()
        handler = _get_handler(router, "create_instance")

        mock_instance = MagicMock()
        mock_instance.id = 50
        mock_instance.save = AsyncMock()

        mock_model_admin = MagicMock()
        mock_model_admin.has_add_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = ["created_at"]

        mock_model = MagicMock()
        mock_model._fields = {}
        mock_model.return_value = mock_instance

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name",
                    return_value=mock_model,
                ):
                    with patch("openviper.admin.api.views.log_change", new_callable=AsyncMock):
                        response = await handler(
                            _mock_request(json_data={"created_at": "2024-01-01", "title": "X"}),
                            model_name="Article",
                        )

        assert response.status_code == 201
        # created_at should NOT be in the kwargs passed to model_class()
        call_kwargs = mock_model.call_args[1] if mock_model.call_args else {}
        assert "created_at" not in call_kwargs


# ---------------------------------------------------------------------------
# get_instance (legacy) – non-primitive field value in response (lines 1196-1197)
# ---------------------------------------------------------------------------


class TestGetInstanceNonPrimitiveField:
    @pytest.mark.asyncio
    async def test_non_primitive_field_converted_to_str_in_response(self):
        """Lines 1196-1197: non-primitive field value is str()-converted in response."""

        class ObjVal:
            def __str__(self):
                return "obj_value"

        router = _make_router()
        handler = _get_handler(router, "get_instance")

        mock_instance = MagicMock()
        mock_instance.id = 99
        mock_instance.data = ObjVal()

        mock_model_admin = MagicMock()
        mock_model_admin.has_view_permission.return_value = True
        mock_model_admin.get_model_info.return_value = {}
        mock_model_admin.get_readonly_fields.return_value = []
        mock_model_admin.get_fieldsets.return_value = []

        mock_model = MagicMock()
        mock_model._fields = {"data": MagicMock()}
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name",
                    return_value=mock_model,
                ):
                    response = await handler(_mock_request(), model_name="Article", obj_id=99)

        body = json.loads(response.body)
        assert body["instance"]["data"] == "obj_value"
