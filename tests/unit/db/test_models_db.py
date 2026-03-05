from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.db import fields
from openviper.db.models import AbstractModel, Model, QuerySet
from openviper.exceptions import DoesNotExist, MultipleObjectsReturned


class EmptyModel(Model):
    name = fields.CharField(default="test")

    class Meta:
        table_name = "test_empty_model"


class BaseModel(AbstractModel):
    is_active = fields.BooleanField(default=True)


class TestModel(BaseModel):
    title = fields.CharField(max_length=10)
    user_id = fields.ForeignKey(to="auth.User")

    class Meta:
        table_name = "test_model_table"


def test_model_metaclass():
    assert "id" in EmptyModel._fields
    assert "name" in EmptyModel._fields
    assert EmptyModel._table_name == "test_empty_model"

    # Inheritance
    assert "is_active" in TestModel._fields
    assert "title" in TestModel._fields
    assert TestModel._table_name == "test_model_table"


def test_model_instantiation():
    m = TestModel(title="Hello", user_id=1, extra_attr=10)
    assert m.title == "Hello"
    assert m.user_id == 1
    assert m.is_active is True
    assert m.extra_attr == 10

    # ID not set
    assert m.id is None
    assert m.pk is None

    # From row
    row = {"id": 5, "title": "Row", "is_active": False, "user_id": 2, "random": 100}
    m2 = TestModel._from_row(row)
    assert m2.id == 5
    assert m2.title == "Row"
    assert m2.is_active is False
    assert m2.random == 100


def test_model_change_tracking():
    m = TestModel(title="Init")
    assert m.has_changed is False

    m.title = "Changed"
    assert m.has_changed is True
    assert m._get_changed_fields() == {"title": "Init"}

    m._previous_state = m._snapshot()
    assert m.has_changed is False


@pytest.mark.asyncio
async def test_model_validation():
    m = TestModel(title="Too Long String Here")
    with (
        patch("openviper.db.models.get_soft_removed_columns", return_value=[]),
        patch("openviper.db.models._load_soft_removed_columns"),
        pytest.raises(ValueError, match="exceeds max_length"),
    ):
        await m.validate()


@pytest.mark.asyncio
async def test_queryset_chaining():
    qs = QuerySet(TestModel)

    qs2 = qs.filter(title="A").exclude(id=5).order_by("-id").limit(10).offset(20)
    assert qs2._filters == [{"title": "A"}]
    assert qs2._excludes == [{"id": 5}]
    assert qs2._order == ["-id"]
    assert qs2._limit == 10
    assert qs2._offset == 20

    # Original unchanged
    assert qs._limit is None


@pytest.mark.asyncio
@patch("openviper.db.models.execute_select")
async def test_queryset_get(mock_select):
    qs = QuerySet(EmptyModel)

    # DoesNotExist
    mock_select.return_value = []
    with pytest.raises(DoesNotExist):
        await qs.get()

    # MultipleObjects
    mock_select.return_value = [{"id": 1}, {"id": 2}]
    with pytest.raises(MultipleObjectsReturned):
        await qs.get()

    # Success
    mock_select.return_value = [{"id": 1, "name": "hi"}]
    m = await qs.get()
    assert m.id == 1
    assert m.name == "hi"


@pytest.mark.asyncio
@patch("openviper.db.models.execute_select")
async def test_queryset_first_last(mock_select):
    qs = QuerySet(EmptyModel).order_by("id")
    mock_select.return_value = [{"id": 10, "name": "First"}]

    m1 = await qs.first()
    assert m1.id == 10

    m2 = await qs.last()
    assert m2.id == 10


@pytest.mark.asyncio
@patch("openviper.db.models.execute_save")
async def test_model_save_lifecycle(mock_save):
    # Patch lifecycle hooks
    for hook in [
        "before_validate",
        "validate",
        "before_insert",
        "before_save",
        "after_insert",
        "on_change",
    ]:
        setattr(EmptyModel, hook, AsyncMock())

    m = EmptyModel(name="test")
    await m.save()

    m.before_validate.assert_called_once()
    m.validate.assert_called_once()
    m.before_insert.assert_called_once()
    m.before_save.assert_called_once()
    m.after_insert.assert_called_once()
    m.on_change.assert_called_once()
    mock_save.assert_called_once_with(m, ignore_permissions=False)


@pytest.mark.asyncio
@patch("openviper.db.models.execute_delete_instance")
async def test_model_delete(mock_delete):
    EmptyModel.on_delete = AsyncMock()
    EmptyModel.after_delete = AsyncMock()

    m = EmptyModel(id=1)
    await m.delete()

    m.on_delete.assert_called_once()
    mock_delete.assert_called_once_with(m, ignore_permissions=False)
    m.after_delete.assert_called_once()


@pytest.mark.asyncio
@patch("openviper.db.models.execute_select")
async def test_queryset_aiter(mock_select):
    mock_select.return_value = [{"id": 1, "name": "hi"}, {"id": 2, "name": "bye"}]
    qs = QuerySet(EmptyModel)

    items = []
    async for item in qs:
        items.append(item)

    assert len(items) == 2
    assert items[0].id == 1
    assert items[1].id == 2


@pytest.mark.asyncio
@patch("openviper.db.models.execute_select")
@patch("openviper.db.models.execute_save")
async def test_manager_get_or_create(mock_save, mock_select):
    mock_select.side_effect = DoesNotExist("missing")

    # Needs create
    obj, created = await EmptyModel.objects.get_or_create(defaults={"name": "new"}, id=10)
    assert created is True
    assert obj.id == 10
    assert obj.name == "new"

    # Already exists
    mock_select.side_effect = None
    mock_select.return_value = [{"id": 10, "name": "existing"}]

    obj2, created2 = await EmptyModel.objects.get_or_create(id=10)
    assert created2 is False
    assert obj2.id == 10
    assert obj2.name == "existing"


@pytest.mark.asyncio
@patch("openviper.db.models.check_permission_for_model")
@patch("openviper.db.models.get_connection")
async def test_manager_bulk_create(mock_conn_factory, mock_check_perm):
    mock_conn = MagicMock()
    mock_ctx = AsyncMock()
    mock_conn.begin.return_value = mock_ctx
    mock_conn.execute = AsyncMock()
    mock_conn_factory.return_value = mock_conn

    m1 = EmptyModel(name="A")
    m2 = EmptyModel(name="B")

    res = await EmptyModel.objects.bulk_create([m1, m2])
    assert res == [m1, m2]
    mock_conn.execute.assert_called_once()


@pytest.mark.asyncio
@patch("openviper.db.models.Manager.get")
async def test_model_refresh_from_db(mock_get):
    fresh = EmptyModel(id=1, name="fresh")
    mock_get.return_value = fresh

    m = EmptyModel(id=1, name="stale")
    await m.refresh_from_db()

    assert m.name == "fresh"
    mock_get.assert_called_once_with(id=1)


def test_model_extract_app_name():
    from openviper.db.models import ModelMeta

    assert ModelMeta._extract_app_name("apps.blog.models", "Post") == "blog"
    assert ModelMeta._extract_app_name("openviper.auth.models", "User") == "auth"
    assert ModelMeta._extract_app_name("something.else", "Blah") == "something"
    assert ModelMeta._extract_app_name("", "Blah") == "default"


@pytest.mark.asyncio
async def test_call_hook_sync_async():
    from openviper.db.models import _call_hook

    def sync_hook():
        return 42

    async def async_hook():
        return 99

    assert await _call_hook(sync_hook) == 42
    assert await _call_hook(async_hook) == 99


@pytest.mark.asyncio
@patch("openviper.db.models.execute_count")
async def test_queryset_exists(mock_count):
    mock_count.return_value = 1
    assert await EmptyModel.objects.all().exists() is True

    mock_count.return_value = 0
    assert await EmptyModel.objects.all().exists() is False


def test_model_eq():
    m1 = EmptyModel(id=1)
    m2 = EmptyModel(id=1)
    m3 = EmptyModel(id=2)
    m_no_id = EmptyModel()

    assert m1 == m2
    assert m1 != m3
    assert m1 != "not a model"
    assert m_no_id != m1


@pytest.mark.asyncio
async def test_manager_delegation():
    # Manager exclude, order_by, get_or_none
    qs1 = EmptyModel.objects.exclude(name="hi")
    assert qs1._excludes == [{"name": "hi"}]

    qs2 = EmptyModel.objects.order_by("name")
    assert qs2._order == ["name"]


@pytest.mark.asyncio
@patch("openviper.db.models.execute_select")
async def test_manager_get_or_none(mock_select):
    mock_select.side_effect = DoesNotExist("err")
    assert await EmptyModel.objects.get_or_none(id=99) is None

    mock_select.side_effect = None
    mock_select.return_value = [{"id": 99, "name": "found"}]
    res = await EmptyModel.objects.get_or_none(id=99)
    assert res.id == 99


@pytest.mark.asyncio
async def test_queryset_related():
    qs = EmptyModel.objects.all().select_related("author").prefetch_related("comments")
    assert qs._select_related == ["author"]
    assert qs._prefetch_related == ["comments"]


@pytest.mark.asyncio
@patch("openviper.db.models.execute_update")
@patch("openviper.db.models.execute_delete")
async def test_queryset_update_delete(mock_del, mock_upd):
    mock_del.return_value = 5
    mock_upd.return_value = 3

    qs = EmptyModel.objects.filter(id=1)
    assert await qs.delete() == 5
    assert await qs.update(name="updated") == 3


@pytest.mark.asyncio
@patch("openviper.db.models.execute_save")
async def test_model_update_lifecycle(mock_save):
    # Testing an update vs create
    m = EmptyModel(id=5, name="old")
    m._previous_state = m._snapshot()

    m.name = "new"  # Modify to trigger change

    await m.save()
    mock_save.assert_called_once()
    # verify on_change tracked old state
    assert m.has_changed is False

    # default hooks (coverage for the default pass-through async defs)
    m2 = EmptyModel()
    await m2.before_insert()
    await m2.after_insert()
    await m2.on_update()
    await m2.before_save()
    await m2.before_validate()
    await m2.on_delete()
    await m2.after_delete()
    await m2.on_change({})


def test_model_kwargs_init():
    # line 436 coverage
    m = EmptyModel(id=1, name="hi")
    EmptyModel(
        id=1, name="hi", extra_arg="ignored"
    )  # Test branch where key not in fields, should be ignored unless hasattr
    assert m.name == "hi"


@pytest.mark.asyncio
@patch("openviper.db.models.execute_select")
async def test_queryset_last_ordered(mock_select):
    qs = EmptyModel.objects.all().order_by("-id", "name")

    mock_select.return_value = [{"id": 3, "name": "three"}]
    res = await qs.last()
    assert res.id == 3


@pytest.mark.asyncio
async def test_validate_skip_auto_date():
    class DateModel(Model):
        created = fields.DateTimeField(auto_now_add=True)
        updated = fields.DateTimeField(auto_now=True)

        class Meta:
            table_name = "date_model"

    m = DateModel()
    with (
        patch("openviper.db.models.get_soft_removed_columns", return_value=[]),
        patch("openviper.db.models._load_soft_removed_columns"),
    ):
        # Should skip validation on created/updated
        await m.validate()

    m._apply_auto_fields()
    assert m.created is not None
    assert m.updated is not None

    # line 507 soft_removed coverage
    with patch("openviper.db.models.get_soft_removed_columns", return_value=["name"]):
        await EmptyModel(
            id=1, name="hi"
        ).validate()  # name is soft removed, shouldn't raise even if invalid
