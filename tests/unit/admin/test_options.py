"""Unit tests for openviper.admin.options (ModelAdmin and related classes)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from openviper.admin.options import (
    ChildTable,
    InlineModelAdmin,
    ModelAdmin,
    StackedInline,
    TabularInline,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_model(
    name: str = "TestModel",
    app_name: str = "testapp",
    table_name: str = "test_table",
    fields: dict | None = None,
) -> type:
    """Return a simple Python class that looks enough like a Openviper Model."""

    class _Model:
        pass

    _Model.__name__ = name
    _Model._app_name = app_name
    _Model._table_name = table_name
    _Model._fields = fields if fields is not None else {}
    return _Model


def make_field(class_name: str = "CharField", **attrs) -> MagicMock:
    field = MagicMock()
    field.__class__.__name__ = class_name
    field.name = attrs.get("name", "some_field")
    field.null = attrs.get("null", False)
    field.blank = attrs.get("blank", False)
    field.unique = attrs.get("unique", False)
    field.db_index = attrs.get("db_index", False)
    field.default = attrs.get("default")
    field.primary_key = attrs.get("primary_key", False)
    field.help_text = attrs.get("help_text", "")
    return field


def make_request(is_staff: bool = False, is_superuser: bool = False, has_user: bool = True):
    req = MagicMock()
    if has_user:
        req.user = MagicMock()
        req.user.is_staff = is_staff
        req.user.is_superuser = is_superuser
    else:
        req.user = None
    return req


# ---------------------------------------------------------------------------
# ModelAdmin.__init__
# ---------------------------------------------------------------------------


class TestModelAdminInit:
    def test_attributes_set_from_model_class(self):
        fields = {"title": make_field("CharField")}
        Model = make_model(name="Post", app_name="blog", table_name="posts", fields=fields)
        admin = ModelAdmin(Model)

        assert admin.model is Model
        assert admin._model_name == "Post"
        assert admin._app_name == "blog"
        assert admin._table_name == "posts"
        assert admin._fields is fields

    def test_defaults_when_attrs_absent(self):
        class Bare:
            __name__ = "Bare"

        admin = ModelAdmin(Bare)
        assert admin._app_name == "default"
        assert admin._table_name == ""
        assert admin._fields == {}

    def test_repr_contains_class_and_model_name(self):
        Model = make_model(name="Article")
        admin = ModelAdmin(Model)
        r = repr(admin)
        assert "ModelAdmin" in r
        assert "Article" in r


# ---------------------------------------------------------------------------
# List-view configuration methods
# ---------------------------------------------------------------------------


class TestGetListDisplay:
    def test_returns_explicit_list_display(self):
        admin = ModelAdmin(make_model())
        admin.list_display = ["id", "name", "email"]
        assert admin.get_list_display() == ["id", "name", "email"]

    def test_default_includes_id_prefix_when_id_not_in_fields(self):
        Model = make_model(fields={"name": make_field(), "bio": make_field("TextField")})
        admin = ModelAdmin(Model)
        admin.list_display = []
        result = admin.get_list_display()
        assert result[0] == "id"
        assert "name" in result

    def test_default_no_duplicate_id_when_id_already_in_fields(self):
        Model = make_model(fields={"id": make_field(), "name": make_field()})
        admin = ModelAdmin(Model)
        admin.list_display = []
        result = admin.get_list_display()
        assert result.count("id") == 1

    def test_default_limits_to_first_five_fields(self):
        fields = {str(i): make_field() for i in range(10)}
        Model = make_model(fields=fields)
        admin = ModelAdmin(Model)
        admin.list_display = []
        result = admin.get_list_display()
        # At most id + 5 = 6 entries (or just 5 if id already in fields)
        assert len(result) <= 6

    def test_request_parameter_accepted(self):
        admin = ModelAdmin(make_model())
        admin.list_display = ["id"]
        assert admin.get_list_display(request=MagicMock()) == ["id"]


class TestGetListDisplayLinks:
    def test_explicit_list_display_links(self):
        admin = ModelAdmin(make_model())
        admin.list_display_links = ["slug"]
        assert admin.get_list_display_links() == ["slug"]

    def test_default_returns_first_item_of_list_display(self):
        admin = ModelAdmin(make_model())
        admin.list_display = ["id", "title"]
        admin.list_display_links = None
        assert admin.get_list_display_links() == ["id"]

    def test_empty_list_display_links_returns_empty(self):
        admin = ModelAdmin(make_model())
        admin.list_display_links = []
        assert admin.get_list_display_links() == []

    def test_default_empty_display_still_returns_list(self):
        Model = make_model(fields={})
        admin = ModelAdmin(Model)
        admin.list_display = []
        admin.list_display_links = None
        result = admin.get_list_display_links()
        assert isinstance(result, list)


class TestGetListFilter:
    def test_returns_list_filter(self):
        admin = ModelAdmin(make_model())
        admin.list_filter = ["status", "created_at"]
        assert admin.get_list_filter() == ["status", "created_at"]

    def test_returns_copy_not_reference(self):
        admin = ModelAdmin(make_model())
        admin.list_filter = ["x"]
        result = admin.get_list_filter()
        result.append("y")
        assert "y" not in admin.list_filter


class TestGetSearchFields:
    def test_returns_search_fields(self):
        admin = ModelAdmin(make_model())
        admin.search_fields = ["name", "email"]
        assert admin.get_search_fields() == ["name", "email"]

    def test_empty_returns_empty_list(self):
        admin = ModelAdmin(make_model())
        admin.search_fields = []
        assert admin.get_search_fields() == []


class TestGetOrdering:
    def test_string_ordering_wrapped_in_list(self):
        admin = ModelAdmin(make_model())
        admin.ordering = "created_at"
        assert admin.get_ordering() == ["created_at"]

    def test_list_ordering_returned_as_list(self):
        admin = ModelAdmin(make_model())
        admin.ordering = ["-created_at", "name"]
        assert admin.get_ordering() == ["-created_at", "name"]

    def test_none_ordering_defaults_to_minus_id(self):
        admin = ModelAdmin(make_model())
        admin.ordering = None
        assert admin.get_ordering() == ["-id"]


# ---------------------------------------------------------------------------
# Form configuration methods
# ---------------------------------------------------------------------------


class TestGetFields:
    def test_explicit_fields_returned(self):
        admin = ModelAdmin(make_model())
        admin.fields = ["name", "email"]
        assert admin.get_fields() == ["name", "email"]

    def test_auto_excludes_id_field(self):
        Model = make_model(fields={"id": make_field(), "name": make_field(), "bio": make_field()})
        admin = ModelAdmin(Model)
        admin.fields = None
        admin.exclude = None
        result = admin.get_fields()
        assert "id" not in result
        assert "name" in result
        assert "bio" in result

    def test_exclude_removes_fields(self):
        Model = make_model(
            fields={"name": make_field(), "secret": make_field(), "bio": make_field()}
        )
        admin = ModelAdmin(Model)
        admin.fields = None
        admin.exclude = ["secret"]
        result = admin.get_fields()
        assert "secret" not in result
        assert "name" in result


class TestGetExclude:
    def test_none_exclude_returns_empty_list(self):
        admin = ModelAdmin(make_model())
        admin.exclude = None
        assert admin.get_exclude() == []

    def test_explicit_exclude_returned(self):
        admin = ModelAdmin(make_model())
        admin.exclude = ["password", "internal"]
        assert admin.get_exclude() == ["password", "internal"]


class TestGetSensitiveFields:
    def test_class_level_sensitive_fields_returned(self):
        admin = ModelAdmin(make_model())
        admin.sensitive_fields = ["password", "token", "key"]
        result = admin.get_sensitive_fields()
        assert result == ["password", "token", "key"]

    def test_default_class_level_contains_password(self):
        admin = ModelAdmin(make_model())
        result = admin.get_sensitive_fields()
        assert "password" in result

    def test_none_sensitive_fields_falls_back_to_model_fields(self):
        """When sensitive_fields is None, fields are derived from the model."""
        Model = make_model(
            fields={
                "name": make_field("CharField"),
                "api_key": make_field("CharField"),
                "secret_token": make_field("CharField"),
            }
        )
        admin = ModelAdmin(Model)
        # Force sensitive_fields to None (override class-level)
        admin.sensitive_fields = None
        result = admin.get_sensitive_fields()
        # The fallback should include fields whose names contain a sensitive keyword
        assert isinstance(result, list)
        assert "api_key" in result or "secret_token" in result


class TestGetReadonlyFields:
    def test_returns_readonly_fields(self):
        admin = ModelAdmin(make_model())
        admin.readonly_fields = ["created_at", "updated_at"]
        assert admin.get_readonly_fields() == ["created_at", "updated_at"]

    def test_returns_copy(self):
        admin = ModelAdmin(make_model())
        admin.readonly_fields = ["x"]
        result = admin.get_readonly_fields()
        result.append("y")
        assert "y" not in admin.readonly_fields


class TestGetFieldsets:
    def test_explicit_fieldsets_returned(self):
        admin = ModelAdmin(make_model())
        admin.fieldsets = [
            ("Basic", {"fields": ["name"]}),
            ("Advanced", {"fields": ["bio"]}),
        ]
        result = admin.get_fieldsets()
        assert len(result) == 2
        assert result[0][0] == "Basic"

    def test_default_creates_single_fieldset_with_all_fields(self):
        Model = make_model(fields={"name": make_field(), "bio": make_field("TextField")})
        admin = ModelAdmin(Model)
        admin.fieldsets = None
        admin.fields = None
        admin.exclude = None
        result = admin.get_fieldsets()
        assert len(result) == 1
        assert result[0][0] is None
        assert "name" in result[0][1]["fields"]
        assert "bio" in result[0][1]["fields"]


class TestGetFormFieldConfig:
    def test_returns_config_when_present(self):
        admin = ModelAdmin(make_model())
        admin.form_fields = {"body": {"widget": "textarea", "rows": 5}}
        assert admin.get_form_field_config("body") == {"widget": "textarea", "rows": 5}

    def test_returns_empty_dict_when_absent(self):
        admin = ModelAdmin(make_model())
        admin.form_fields = {}
        assert admin.get_form_field_config("unknown") == {}


# ---------------------------------------------------------------------------
# Permission methods
# ---------------------------------------------------------------------------


class TestPermissions:
    # --- has_view_permission ---

    def test_view_no_request_returns_true(self):
        assert ModelAdmin(make_model()).has_view_permission(None) is True

    def test_view_no_user_returns_false(self):
        assert ModelAdmin(make_model()).has_view_permission(make_request(has_user=False)) is False

    def test_view_staff_returns_true(self):
        assert ModelAdmin(make_model()).has_view_permission(make_request(is_staff=True)) is True

    def test_view_superuser_returns_true(self):
        assert ModelAdmin(make_model()).has_view_permission(make_request(is_superuser=True)) is True

    def test_view_regular_user_returns_false(self):
        assert ModelAdmin(make_model()).has_view_permission(make_request()) is False

    # --- has_add_permission ---

    def test_add_no_request_returns_true(self):
        assert ModelAdmin(make_model()).has_add_permission(None) is True

    def test_add_no_user_returns_false(self):
        assert ModelAdmin(make_model()).has_add_permission(make_request(has_user=False)) is False

    def test_add_staff_returns_true(self):
        assert ModelAdmin(make_model()).has_add_permission(make_request(is_staff=True)) is True

    def test_add_regular_user_returns_false(self):
        assert ModelAdmin(make_model()).has_add_permission(make_request()) is False

    # --- has_change_permission ---

    def test_change_no_request_returns_true(self):
        assert ModelAdmin(make_model()).has_change_permission(None) is True

    def test_change_no_user_returns_false(self):
        assert ModelAdmin(make_model()).has_change_permission(make_request(has_user=False)) is False

    def test_change_superuser_returns_true(self):
        assert (
            ModelAdmin(make_model()).has_change_permission(make_request(is_superuser=True)) is True
        )

    def test_change_regular_user_returns_false(self):
        assert ModelAdmin(make_model()).has_change_permission(make_request()) is False

    # --- has_delete_permission ---

    def test_delete_no_request_returns_true(self):
        assert ModelAdmin(make_model()).has_delete_permission(None) is True

    def test_delete_no_user_returns_false(self):
        assert ModelAdmin(make_model()).has_delete_permission(make_request(has_user=False)) is False

    def test_delete_staff_returns_true(self):
        assert ModelAdmin(make_model()).has_delete_permission(make_request(is_staff=True)) is True

    def test_delete_regular_user_returns_false(self):
        assert ModelAdmin(make_model()).has_delete_permission(make_request()) is False


# ---------------------------------------------------------------------------
# Async CRUD methods
# ---------------------------------------------------------------------------


class TestSaveModel:
    async def test_applies_non_readonly_form_data(self):
        admin = ModelAdmin(make_model())
        admin.readonly_fields = ["created_at"]

        obj = MagicMock()
        obj.save = AsyncMock()
        req = MagicMock()

        form_data = {"name": "New Name", "bio": "Hello", "created_at": "never"}
        await admin.save_model(req, obj, form_data, change=False)

        assert obj.name == "New Name"
        assert obj.bio == "Hello"
        obj.save.assert_awaited_once()

    async def test_readonly_fields_are_not_set(self):
        admin = ModelAdmin(make_model())
        admin.readonly_fields = ["created_at"]

        obj = MagicMock()
        obj.save = AsyncMock()
        req = MagicMock()

        # Capture the auto-created child mock before save so we can check it isn't replaced
        original_created_at = obj.created_at

        await admin.save_model(req, obj, {"name": "updated", "created_at": "SHOULD_NOT_SET"})

        # Readonly 'created_at' should not have been overwritten
        assert obj.created_at is original_created_at
        # Non-readonly 'name' was applied
        assert obj.name == "updated"
        obj.save.assert_awaited_once()

    async def test_returns_saved_object(self):
        admin = ModelAdmin(make_model())
        obj = MagicMock()
        obj.save = AsyncMock()
        result = await admin.save_model(MagicMock(), obj, {})
        assert result is obj


class TestDeleteModel:
    async def test_delete_calls_obj_delete(self):
        admin = ModelAdmin(make_model())
        obj = MagicMock()
        obj.delete = AsyncMock()
        await admin.delete_model(MagicMock(), obj)
        obj.delete.assert_awaited_once()


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


class TestGetActions:
    def test_always_includes_delete_selected(self):
        admin = ModelAdmin(make_model())
        actions = admin.get_actions()
        assert "delete_selected" in actions

    def test_callable_action_included_by_func_name(self):
        def my_export(request, queryset):
            pass

        admin = ModelAdmin(make_model())
        admin.actions = [my_export]
        actions = admin.get_actions()
        assert "my_export" in actions

    def test_string_action_resolved_to_method(self):
        admin = ModelAdmin(make_model())
        admin.my_bulk_action = lambda req, qs: None
        admin.actions = ["my_bulk_action"]
        actions = admin.get_actions()
        assert "my_bulk_action" in actions

    def test_string_action_invalid_logs_warning(self):
        admin = ModelAdmin(make_model())
        admin.actions = ["definitely_not_a_real_method"]
        # create=True handles the case where logger isn't defined at module level
        with patch("openviper.admin.options.logger", create=True) as mock_logger:
            admin.get_actions()
            mock_logger.warning.assert_called_once()

    def test_string_action_invalid_not_in_actions(self):
        admin = ModelAdmin(make_model())
        admin.actions = ["doesnt_exist"]
        with patch("openviper.admin.options.logger", create=True):
            actions = admin.get_actions()
        assert "doesnt_exist" not in actions

    def test_multiple_actions(self):
        def action_a(req, qs):
            pass

        def action_b(req, qs):
            pass

        admin = ModelAdmin(make_model())
        admin.actions = [action_a, action_b]
        actions = admin.get_actions()
        assert "action_a" in actions
        assert "action_b" in actions


class TestActionDeleteSelected:
    async def test_deletes_and_returns_count(self):
        admin = ModelAdmin(make_model())
        qs = MagicMock()
        qs.count = AsyncMock(return_value=3)
        qs.delete = AsyncMock()

        count = await admin._action_delete_selected(MagicMock(), qs)

        assert count == 3
        qs.delete.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_model_info
# ---------------------------------------------------------------------------


class TestGetModelInfo:
    def test_basic_structure(self):
        Model = make_model(name="Post", app_name="blog", table_name="blog_post")
        admin = ModelAdmin(Model)
        admin.list_display = ["id", "title"]
        admin.list_filter = ["published"]
        admin.search_fields = ["title"]
        admin.readonly_fields = ["created_at"]
        admin.fieldsets = None
        admin.fields = None
        admin.exclude = None

        with patch("openviper.admin.options.get_field_schema", return_value={"type": "unknown"}):
            info = admin.get_model_info()

        assert info["name"] == "Post"
        assert info["app"] == "blog"
        assert info["table"] == "blog_post"
        assert info["list_display"] == ["id", "title"]
        assert info["list_filter"] == ["published"]
        assert info["search_fields"] == ["title"]
        assert "delete_selected" in info["actions"]
        assert info["list_per_page"] == 25
        assert "fields" in info
        assert "fieldsets" in info

    def test_sensitive_fields_excluded_from_fields_info(self):
        Model = make_model(
            fields={
                "email": make_field("EmailField"),
                "password": make_field("CharField"),
            }
        )
        admin = ModelAdmin(Model)
        admin.sensitive_fields = ["password"]
        admin.exclude = []
        admin.fields = None
        admin.fieldsets = None

        with patch("openviper.admin.options.get_field_schema", return_value={"type": "text"}):
            info = admin.get_model_info()

        assert "password" not in info["fields"]
        assert "email" in info["fields"]

    def test_excluded_fields_not_in_fields_info(self):
        Model = make_model(
            fields={
                "name": make_field("CharField"),
                "internal": make_field("IntegerField"),
            }
        )
        admin = ModelAdmin(Model)
        admin.sensitive_fields = []
        admin.exclude = ["internal"]
        admin.fields = None
        admin.fieldsets = None

        with patch("openviper.admin.options.get_field_schema", return_value={}):
            info = admin.get_model_info()

        assert "internal" not in info["fields"]

    def test_fieldsets_sensitive_filtered_out(self):
        admin = ModelAdmin(make_model())
        admin.fieldsets = [
            ("Section", {"fields": ["name", "password"]}),
        ]
        admin.sensitive_fields = ["password"]
        admin.exclude = []
        admin.fields = None

        with patch("openviper.admin.options.get_field_schema", return_value={}):
            info = admin.get_model_info()

        if info["fieldsets"]:
            for fs in info["fieldsets"]:
                assert "password" not in fs["fields"]

    def test_all_fieldset_fields_sensitive_returns_none(self):
        admin = ModelAdmin(make_model())
        admin.fieldsets = [
            ("Secrets", {"fields": ["password"]}),
        ]
        admin.sensitive_fields = ["password"]
        admin.exclude = []
        admin.fields = None

        with patch("openviper.admin.options.get_field_schema", return_value={}):
            info = admin.get_model_info()

        assert info["fieldsets"] is None

    def test_verbose_name_plural(self):
        Model = make_model(name="Article")
        admin = ModelAdmin(Model)
        admin.fields = None
        admin.exclude = None
        admin.fieldsets = None

        with patch("openviper.admin.options.get_field_schema", return_value={}):
            info = admin.get_model_info()

        assert info["verbose_name_plural"] == "Articles"

    def test_readonly_fields_in_info(self):
        admin = ModelAdmin(make_model())
        admin.readonly_fields = ["created_at", "updated_at"]
        admin.fields = None
        admin.exclude = None
        admin.fieldsets = None

        with patch("openviper.admin.options.get_field_schema", return_value={}):
            info = admin.get_model_info()

        assert info["readonly_fields"] == ["created_at", "updated_at"]


# ---------------------------------------------------------------------------
# get_child_tables_info
# ---------------------------------------------------------------------------


class TestGetChildTablesInfo:
    def test_empty_returns_empty_list(self):
        admin = ModelAdmin(make_model())
        admin.child_tables = []
        admin.inlines = []
        assert admin.get_child_tables_info() == []

    def test_uses_inlines_when_child_tables_empty(self):
        ParentModel = make_model(name="Post")
        ChildModel = make_model(
            name="Comment",
            fields={"body": make_field("TextField")},
        )

        class CommentInline(TabularInline):
            model = ChildModel
            fk_name = "post"
            fields = ["body"]
            readonly_fields = []

        admin = ModelAdmin(ParentModel)
        admin.child_tables = []
        admin.inlines = [CommentInline]

        with patch("openviper.admin.options.get_field_schema", return_value={"type": "text"}):
            result = admin.get_child_tables_info()

        assert len(result) == 1
        assert result[0]["model"] == "Comment"
        assert result[0]["fk_name"] == "post"

    def test_uses_child_tables_list(self):
        ParentModel = make_model(name="Order")
        ItemModel = make_model(name="OrderItem", fields={"qty": make_field("IntegerField")})

        class ItemInline(ChildTable):
            model = ItemModel
            fk_name = "order"
            fields = ["qty"]
            readonly_fields = []

        admin = ModelAdmin(ParentModel)
        admin.child_tables = [ItemInline]

        with patch("openviper.admin.options.get_field_schema", return_value={}):
            result = admin.get_child_tables_info()

        assert len(result) == 1
        assert result[0]["model"] == "OrderItem"

    def test_inline_fields_none_uses_all_model_fields(self):
        ParentModel = make_model()
        ChildModel = make_model(
            name="Tag",
            fields={"name": make_field(), "slug": make_field()},
        )

        class TagInline(TabularInline):
            model = ChildModel
            fk_name = "post"
            fields = None
            readonly_fields = []

        admin = ModelAdmin(ParentModel)
        admin.child_tables = [TagInline]
        admin.inlines = []

        with patch("openviper.admin.options.get_field_schema", return_value={}):
            result = admin.get_child_tables_info()

        display_fields = result[0]["display_fields"]
        # id is prepended automatically
        assert "id" in display_fields
        assert "name" in display_fields
        assert "slug" in display_fields

    def test_inline_readonly_fields_propagated(self):
        ParentModel = make_model()
        ChildModel = make_model(name="Child", fields={})

        class MyInline(ChildTable):
            model = ChildModel
            fk_name = "parent"
            fields = []
            readonly_fields = ["created_at"]

        admin = ModelAdmin(ParentModel)
        admin.child_tables = [MyInline]

        with patch("openviper.admin.options.get_field_schema", return_value={}):
            result = admin.get_child_tables_info()

        assert result[0]["readonly_fields"] == ["created_at"]

    def test_child_table_name_convention(self):
        """name should follow the '<model>_set' convention."""
        ParentModel = make_model()
        ChildModel = make_model(name="Photo", fields={})

        class PhotoInline(ChildTable):
            model = ChildModel
            fk_name = "album"
            fields = []
            readonly_fields = []

        admin = ModelAdmin(ParentModel)
        admin.child_tables = [PhotoInline]

        with patch("openviper.admin.options.get_field_schema", return_value={}):
            result = admin.get_child_tables_info()

        assert result[0]["name"] == "photo_set"


# ---------------------------------------------------------------------------
# Inline / Tabular / Stacked / ChildTable classes
# ---------------------------------------------------------------------------


class TestInlineClasses:
    def test_tabular_inline_has_correct_template(self):
        assert TabularInline.template == "tabular"

    def test_stacked_inline_has_correct_template(self):
        assert StackedInline.template == "stacked"

    def test_child_table_is_tabular_inline_subclass(self):
        assert issubclass(ChildTable, TabularInline)

    def test_inline_model_admin_defaults(self):
        assert InlineModelAdmin.extra == 3
        assert InlineModelAdmin.can_delete is True
        assert InlineModelAdmin.show_change_link is False
        assert InlineModelAdmin.readonly_fields == []

    def test_inline_init_stores_parent_model(self):
        ParentModel = make_model(name="Parent")
        ChildModel = make_model(name="Child")

        class MyInline(InlineModelAdmin):
            model = ChildModel
            fk_name = "parent"

        inline = MyInline(ParentModel)
        assert inline.parent_model is ParentModel

    def test_tabular_inline_init(self):
        ParentModel = make_model()
        ChildModel = make_model()

        class TI(TabularInline):
            model = ChildModel
            fk_name = "ref"

        ti = TI(ParentModel)
        assert ti.parent_model is ParentModel
        assert TI.template == "tabular"

    def test_stacked_inline_init(self):
        ParentModel = make_model()
        ChildModel = make_model()

        class SI(StackedInline):
            model = ChildModel
            fk_name = "ref"

        si = SI(ParentModel)
        assert si.parent_model is ParentModel
        assert SI.template == "stacked"
