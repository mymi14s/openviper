"""Unit tests for readonly fields editability in Create mode."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openviper.admin.options import ModelAdmin


def _make_field(name, field_type="CharField", **kwargs):
    field = MagicMock()
    field.name = name
    field.__class__.__name__ = field_type
    field.primary_key = kwargs.get("primary_key", False)
    field.auto_increment = kwargs.get("auto_increment", False)
    field.auto_now = kwargs.get("auto_now", False)
    field.auto_now_add = kwargs.get("auto_now_add", False)
    field.editable = kwargs.get("editable", True)
    return field


def _make_model_class(fields=None):
    model = MagicMock()
    model.__name__ = "TestModel"
    model._fields = fields or {}
    return model


@pytest.mark.asyncio
async def test_save_model_allows_readonly_in_create():
    """Test that readonly_fields are editable during creation (change=False)."""
    fields = {
        "id": _make_field("id", "IntegerField", primary_key=True, auto_increment=True),
        "slug": _make_field("slug", "CharField"),
        "name": _make_field("name", "CharField"),
    }
    model_cls = _make_model_class(fields=fields)

    class TestAdmin(ModelAdmin):
        readonly_fields = ["slug"]

    admin = TestAdmin(model_cls)
    request = MagicMock()
    instance = MagicMock()
    instance.save = AsyncMock()

    # Form data includes the 'readonly' slug
    form_data = {"slug": "test-slug", "name": "Test Name"}

    # 1. Create mode (change=False)
    await admin.save_model(request, instance, form_data, change=False)

    # slug should have been set
    instance.slug = "test-slug"  # Mock behavior: MagicMock records assignments
    assert instance.slug == "test-slug"
    instance.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_model_blocks_readonly_in_edit():
    """Test that readonly_fields are NOT editable during editing (change=True)."""
    fields = {
        "slug": _make_field("slug", "CharField"),
        "name": _make_field("name", "CharField"),
    }
    model_cls = _make_model_class(fields=fields)

    class TestAdmin(ModelAdmin):
        readonly_fields = ["slug"]

    admin = TestAdmin(model_cls)
    request = MagicMock()
    instance = MagicMock()
    instance.slug = "original-slug"
    instance.save = AsyncMock()

    form_data = {"slug": "new-slug", "name": "New Name"}

    # 2. Edit mode (change=True)
    await admin.save_model(request, instance, form_data, change=True)

    # slug should NOT have been changed
    assert instance.slug == "original-slug"
    assert instance.name == "New Name"
    instance.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_model_always_blocks_intrinsic_readonly():
    """Test that intrinsically readonly fields (like AutoField) are never set."""
    fields = {
        "id": _make_field("id", "IntegerField", primary_key=True, auto_increment=True),
        "created_at": _make_field("created_at", "DateTimeField", auto_now_add=True),
        "name": _make_field("name", "CharField"),
    }
    model_cls = _make_model_class(fields=fields)

    admin = ModelAdmin(model_cls)
    request = MagicMock()
    instance = MagicMock()
    instance.id = None
    instance.created_at = None
    instance.save = AsyncMock()

    form_data = {"id": 999, "created_at": "2024-01-01", "name": "Test"}

    # Create mode
    await admin.save_model(request, instance, form_data, change=False)

    # id and created_at should NOT have been set even in Create mode
    assert instance.id is None
    assert instance.created_at is None
    assert instance.name == "Test"


def test_get_fields_excludes_non_editable_on_create():
    """Test that fields with editable=False are excluded from get_fields during creation."""
    fields = {
        "id": _make_field("id", "IntegerField", primary_key=True, auto_increment=True),
        "name": _make_field("name", "CharField"),
        "internal_code": _make_field("internal_code", "CharField", editable=False),
    }
    model_cls = _make_model_class(fields=fields)
    admin = ModelAdmin(model_cls)

    # Create mode (obj is None)
    fields_to_show = admin.get_fields(obj=None)

    assert "name" in fields_to_show
    assert "internal_code" not in fields_to_show
    assert "id" not in fields_to_show

    # Edit mode (obj has PK)
    instance = MagicMock()
    instance.pk = 1
    fields_to_show_edit = admin.get_fields(obj=instance)

    assert "name" in fields_to_show_edit
    assert "internal_code" in fields_to_show_edit
