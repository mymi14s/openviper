"""Unit tests for openviper.admin.options — ModelAdmin configuration class."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.admin.options import (
    ChildTable,
    InlineModelAdmin,
    ModelAdmin,
    StackedInline,
    TabularInline,
)


def _make_request(user=None):
    """Create a mock request."""
    request = MagicMock()
    request.user = user
    return request


def _make_user(is_authenticated=True, is_staff=False, is_superuser=False):
    """Create a mock user."""
    user = MagicMock()
    user.is_authenticated = is_authenticated
    user.is_staff = is_staff
    user.is_superuser = is_superuser
    return user


def _make_model_class(name="TestModel", app_name="test", fields=None):
    """Create a mock model class."""
    model = MagicMock()
    model.__name__ = name
    model._app_name = app_name
    model._table_name = name.lower()
    model._fields = fields or {}
    return model


def _make_field(name, field_type="CharField"):
    """Create a mock field."""
    field = MagicMock()
    field.name = name
    field.__class__.__name__ = field_type
    field.null = False
    field.blank = False
    field._column_type = "TEXT"
    field.primary_key = False
    field.unique = False
    field.db_index = False
    field.default = None
    return field


class TestModelAdminInitialization:
    """Test ModelAdmin initialization."""

    def test_initialization_with_model(self):
        """Test that ModelAdmin initializes with model."""
        model = _make_model_class("User", "auth")
        admin = ModelAdmin(model)

        assert admin.model is model
        assert admin._model_name == "User"
        assert admin._app_name == "auth"
        assert admin._table_name == "user"

    def test_initialization_caches_model_info(self):
        """Test that model info is cached."""
        model = _make_model_class()
        admin = ModelAdmin(model)

        assert admin._cached_model_info is None  # Not cached yet


class TestListViewMethods:
    """Test list view configuration methods."""

    def test_get_list_display_default(self):
        """Test default list_display."""
        fields = {"name": _make_field("name"), "email": _make_field("email")}
        model = _make_model_class(fields=fields)
        admin = ModelAdmin(model)

        display = admin.get_list_display()
        assert "id" in display or len(display) > 0

    def test_get_list_display_custom(self):
        """Test custom list_display."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        admin.list_display = ["id", "name", "email"]

        display = admin.get_list_display()
        assert display == ["id", "name", "email"]

    def test_get_list_display_caching(self):
        """Test that list_display is cached."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        admin.list_display = ["id", "name"]

        display1 = admin.get_list_display()
        display2 = admin.get_list_display()

        assert display1 is display2  # Same object reference

    def test_get_list_display_links_default(self):
        """Test default list_display_links."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        admin.list_display = ["id", "name"]

        links = admin.get_list_display_links()
        assert links == ["id"]  # First field

    def test_get_list_display_links_custom(self):
        """Test custom list_display_links."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        admin.list_display_links = ["name", "email"]

        links = admin.get_list_display_links()
        assert links == ["name", "email"]

    def test_get_list_filter(self):
        """Test get_list_filter."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        admin.list_filter = ["is_active", "created_at"]

        filters = admin.get_list_filter()
        assert filters == ["is_active", "created_at"]

        # Test cache
        assert admin.get_list_filter() is filters

    def test_get_search_fields(self):
        """Test get_search_fields."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        admin.search_fields = ["name", "email"]

        fields = admin.get_search_fields()
        assert fields == ["name", "email"]

        # Test cache
        assert admin.get_search_fields() is fields

    def test_get_ordering_string(self):
        """Test get_ordering with string."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        admin.ordering = "name"

        ordering = admin.get_ordering()
        assert ordering == ["name"]

    def test_get_ordering_list(self):
        """Test get_ordering with list."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        admin.ordering = ["name", "-created_at"]

        ordering = admin.get_ordering()
        assert ordering == ["name", "-created_at"]

    def test_get_ordering_default(self):
        """Test default ordering."""
        model = _make_model_class()
        admin = ModelAdmin(model)

        ordering = admin.get_ordering()
        assert ordering == ["-id"]

        # Test cache
        assert admin.get_ordering() is ordering

    def test_get_list_select_related_boolean_true(self):
        """Test auto-detection of foreign keys."""
        fk_field = _make_field("author", "ForeignKey")
        fields = {"author": fk_field, "title": _make_field("title")}
        model = _make_model_class(fields=fields)
        admin = ModelAdmin(model)
        admin.list_select_related = True
        admin.list_display = ["author", "title"]

        related = admin.get_list_select_related()
        assert "author" in related

    def test_get_list_select_related_list(self):
        """Test explicit list of related fields."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        admin.list_select_related = ["author", "category"]

        related = admin.get_list_select_related()
        assert related == ["author", "category"]

        # Test cache
        assert admin.get_list_select_related() is related

    def test_get_list_select_related_boolean_false(self):
        """Test list_select_related = False."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        admin.list_select_related = False
        assert admin.get_list_select_related() == []


class TestFormViewMethods:
    """Test form view configuration methods."""

    def test_get_fields_custom(self):
        """Test custom fields."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        admin.fields = ["name", "email"]

        fields = admin.get_fields()
        assert fields == ["name", "email"]

    def test_get_fields_default(self):
        """Test default fields (all except excluded)."""
        fields_dict = {"name": _make_field("name"), "email": _make_field("email")}
        model = _make_model_class(fields=fields_dict)
        admin = ModelAdmin(model)

        fields = admin.get_fields()
        assert "name" in fields
        assert "email" in fields
        assert "id" not in fields  # Auto-fields excluded

    def test_get_exclude(self):
        """Test get_exclude."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        admin.exclude = ["password"]

        excluded = admin.get_exclude()
        assert excluded == ["password"]

    def test_get_readonly_fields(self):
        """Test get_readonly_fields."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        admin.readonly_fields = ["created_at", "updated_at"]

        readonly = admin.get_readonly_fields()
        assert readonly == ["created_at", "updated_at"]

    def test_get_sensitive_fields(self):
        """Test get_sensitive_fields."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        admin.sensitive_fields = ["password"]

        sensitive = admin.get_sensitive_fields()
        assert "password" in sensitive

    def test_get_sensitive_fields_default_logic(self):
        """Test get_sensitive_fields default wildcard logic."""
        fields_dict = {
            "name": _make_field("name"),
            "user_password": _make_field("user_password"),
            "auth_token": _make_field("auth_token"),
            "api_key": _make_field("api_key"),
        }
        model = _make_model_class("User", fields=fields_dict)
        admin = ModelAdmin(model)
        admin.sensitive_fields = None
        # sensitive_fields is now None, should fallback to default checking

        sensitive = admin.get_sensitive_fields(obj=model)
        assert "user_password" in sensitive
        assert "auth_token" in sensitive
        assert "api_key" in sensitive
        assert "name" not in sensitive

    def test_get_fieldsets_custom(self):
        """Test custom fieldsets."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        admin.fieldsets = [
            ("Personal", {"fields": ["name", "email"]}),
            ("Status", {"fields": ["is_active"]}),
        ]

        fieldsets = admin.get_fieldsets()
        assert len(fieldsets) == 2
        assert fieldsets[0][0] == "Personal"

    def test_get_fieldsets_default(self):
        """Test default fieldsets."""
        fields_dict = {"name": _make_field("name")}
        model = _make_model_class(fields=fields_dict)
        admin = ModelAdmin(model)

        fieldsets = admin.get_fieldsets()
        assert len(fieldsets) == 1
        assert fieldsets[0][0] is None  # No title

    def test_get_form_field_config(self):
        """Test get_form_field_config."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        admin.form_fields = {"name": {"max_length": 100}}

        config = admin.get_form_field_config("name")
        assert config == {"max_length": 100}


class TestPermissionMethods:
    """Test permission checking methods."""

    def test_has_view_permission_staff(self):
        """Test view permission for staff."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        user = _make_user(is_staff=True)
        request = _make_request(user)

        assert admin.has_view_permission(request) is True

    def test_has_view_permission_superuser(self):
        """Test view permission for superuser."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        user = _make_user(is_superuser=True)
        request = _make_request(user)

        assert admin.has_view_permission(request) is True

    def test_has_view_permission_regular_user(self):
        """Test view permission for regular user."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        user = _make_user(is_staff=False)
        request = _make_request(user)

        assert admin.has_view_permission(request) is False

    def test_permissions_with_none_user(self):
        """Test permissions when request.user is None."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        request = _make_request(user=None)

        assert admin.has_view_permission(request) is False
        assert admin.has_add_permission(request) is False
        assert admin.has_change_permission(request) is False
        assert admin.has_delete_permission(request) is False

    def test_has_add_permission(self):
        """Test add permission."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        user = _make_user(is_staff=True)
        request = _make_request(user)

        assert admin.has_add_permission(request) is True

    def test_has_change_permission(self):
        """Test change permission."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        user = _make_user(is_staff=True)
        request = _make_request(user)

        assert admin.has_change_permission(request) is True

    def test_has_delete_permission(self):
        """Test delete permission."""
        model = _make_model_class()
        admin = ModelAdmin(model)
        user = _make_user(is_staff=True)
        request = _make_request(user)

        assert admin.has_delete_permission(request) is True

    def test_permissions_without_request(self):
        """Test permissions default to True without request."""
        model = _make_model_class()
        admin = ModelAdmin(model)

        assert admin.has_view_permission() is True
        assert admin.has_add_permission() is True


class TestCRUDMethods:
    """Test CRUD operation methods."""

    @pytest.mark.asyncio
    async def test_save_model(self):
        """Test save_model method."""
        model_instance = MagicMock()
        model_instance.save = AsyncMock()

        model = _make_model_class()
        admin = ModelAdmin(model)
        request = _make_request()

        form_data = {"name": "Test", "email": "test@example.com"}
        result = await admin.save_model(request, model_instance, form_data)

        model_instance.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_model(self):
        """Test delete_model method."""
        model_instance = MagicMock()
        model_instance.delete = AsyncMock()

        model = _make_model_class()
        admin = ModelAdmin(model)
        request = _make_request()

        await admin.delete_model(request, model_instance)

        model_instance.delete.assert_awaited_once()


class TestActionMethods:
    """Test action-related methods."""

    def test_get_actions_default(self):
        """Test default actions."""
        model = _make_model_class()
        admin = ModelAdmin(model)

        actions = admin.get_actions()
        assert "delete_selected" in actions

    def test_get_actions_custom(self):
        """Test custom actions."""
        model = _make_model_class()

        class CustomAdmin(ModelAdmin):
            def string_action(self, request, queryset):
                pass

        admin = CustomAdmin(model)

        def custom_action(request, queryset):
            pass

        admin.actions = [custom_action, "string_action", "missing_action"]

        with patch("openviper.admin.options.logger.warning") as mock_warning:
            actions = admin.get_actions()
            assert "custom_action" in actions
            assert "string_action" in actions
            assert "missing_action" not in actions
            mock_warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_action_delete_selected(self):
        """Test built-in delete_selected action."""
        model = _make_model_class()
        admin = ModelAdmin(model)

        queryset = MagicMock()
        queryset.count = AsyncMock(return_value=3)
        queryset.delete = AsyncMock()

        request = _make_request()
        count = await admin._action_delete_selected(request, queryset)

        assert count == 3
        queryset.delete.assert_awaited_once()


class TestModelInfoMethod:
    """Test get_model_info method."""

    def test_get_model_info_structure(self):
        """Test model info structure."""
        fields_dict = {"name": _make_field("name")}
        model = _make_model_class("User", "auth", fields_dict)
        admin = ModelAdmin(model)

        info = admin.get_model_info()

        assert "name" in info
        assert "app" in info
        assert "table" in info
        assert "fields" in info
        assert "permissions" in info

    def test_get_model_info_caching(self):
        """Test that model info is cached."""
        model = _make_model_class()
        admin = ModelAdmin(model)

        info1 = admin.get_model_info()
        info2 = admin.get_model_info()

        # Should return same cached data (permissions may differ)
        assert info1["name"] == info2["name"]

    def test_get_model_info_sensitive_fields_excluded(self):
        """Test sensitive fields are excluded from returned info."""
        fields_dict = {"name": _make_field("name"), "password": _make_field("password")}
        model = _make_model_class(fields=fields_dict)
        admin = ModelAdmin(model)
        # Default sensitive fields include 'password'

        info = admin.get_model_info()
        assert "name" in info["fields"]
        assert "password" not in info["fields"]


class TestInlineModelAdmin:
    """Test InlineModelAdmin class."""

    def test_initialization(self):
        """Test inline initialization."""
        parent_model = _make_model_class("Parent")
        child_model = _make_model_class("Child")

        class TestInline(InlineModelAdmin):
            model = child_model

        inline = TestInline(parent_model)
        assert inline.parent_model is parent_model
        assert inline.model is child_model

    def test_default_attributes(self):
        """Test default inline attributes."""
        parent_model = _make_model_class()

        inline = InlineModelAdmin(parent_model)
        assert inline.extra == 3
        assert inline.can_delete is True
        assert inline.show_change_link is False


class TestTabularInline:
    """Test TabularInline class."""

    def test_template_attribute(self):
        """Test that TabularInline has correct template."""
        parent_model = _make_model_class()
        inline = TabularInline(parent_model)
        assert inline.template == "tabular"


class TestStackedInline:
    """Test StackedInline class."""

    def test_template_attribute(self):
        """Test that StackedInline has correct template."""
        parent_model = _make_model_class()
        inline = StackedInline(parent_model)
        assert inline.template == "stacked"


class TestChildTable:
    """Test ChildTable class (alias for TabularInline)."""

    def test_is_tabular_inline_subclass(self):
        """Test that ChildTable is a TabularInline."""
        assert issubclass(ChildTable, TabularInline)

    def test_functionality(self):
        """Test that ChildTable works like TabularInline."""
        parent_model = _make_model_class()
        child = ChildTable(parent_model)
        assert child.template == "tabular"

    def test_get_child_tables_info(self):
        parent_model = _make_model_class()
        child_model = _make_model_class("Child")
        child_model._fields = {"id": _make_field("id"), "name": _make_field("name")}

        class TestChildTable(ChildTable):
            model = child_model
            fields = ["name"]

        admin = ModelAdmin(parent_model)
        admin.child_tables = [TestChildTable]

        child_tables_info = admin.get_child_tables_info()
        assert len(child_tables_info) == 1
        assert child_tables_info[0]["model"] == "Child"
        assert "name" in child_tables_info[0]["fields"]
        assert "id" in child_tables_info[0]["display_fields"]


class TestModelAdminRepr:
    """Test __repr__ method."""

    def test_repr(self):
        """Test string representation."""
        model = _make_model_class("User")
        admin = ModelAdmin(model)

        repr_str = repr(admin)
        assert "ModelAdmin" in repr_str
        assert "User" in repr_str
