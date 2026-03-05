from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.permissions import PermissionError as ModelPermissionError
from openviper.db.fields import CharField, IntegerField
from openviper.db.models import DoesNotExist, Model


class SampleModel(Model):
    _app_name = "myapp"
    _model_name = "Sample"
    _table_name = "sample"
    name = CharField()
    age = IntegerField()

@pytest.fixture(autouse=True)
async def setup_db():
    from openviper.db.connection import get_engine
    engine = await get_engine()
    async with engine.begin() as conn:
        # Simple manual table create for SampleModel
        await conn.execute(sa.text("CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)"))
    yield
    async with engine.begin() as conn:
        await conn.execute(sa.text("DROP TABLE sample"))

import sqlalchemy as sa


@pytest.mark.asyncio
async def test_model_ignore_permissions():
    mgr = SampleModel.objects
    mock_conn = MagicMock()
    mock_conn.begin.return_value.__aenter__ = AsyncMock()
    mock_conn.begin.return_value.__aexit__ = AsyncMock()
    mock_conn.execute = AsyncMock()

    # Mocking lower level functions to avoid db issues
    with patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock) as mock_check:
        with patch("openviper.db.models.get_connection", new_callable=AsyncMock, return_value=mock_conn):
            # bulk_create
            await mgr.bulk_create([SampleModel(name="test")], ignore_permissions=True)
            mock_check.assert_any_call(SampleModel, "create", ignore_permissions=True)

            # QuerySet.all ignore_permissions
            qs = mgr.filter(name="test", ignore_permissions=True)
            with patch("openviper.db.models.execute_select", new_callable=AsyncMock, return_value=[]):
                await qs.all()
                mock_check.assert_any_call(SampleModel, "read", ignore_permissions=True)

            # first()
            with patch("openviper.db.models.execute_select", new_callable=AsyncMock, return_value=[]):
                await qs.first()
                mock_check.assert_any_call(SampleModel, "read", ignore_permissions=True)

            # count()
            with patch("openviper.db.models.execute_count", new_callable=AsyncMock, return_value=0):
                await qs.count()
                mock_check.assert_any_call(SampleModel, "read", ignore_permissions=True)

            # exists()
            with patch("openviper.db.models.execute_count", new_callable=AsyncMock, return_value=0):
                await qs.exists()
                mock_check.assert_any_call(SampleModel, "read", ignore_permissions=True)

            # update()
            with patch("openviper.db.models.execute_update", new_callable=AsyncMock, return_value=0):
                await qs.update(name="new")
                mock_check.assert_any_call(SampleModel, "update", ignore_permissions=True)

            # delete()
            with patch("openviper.db.models.execute_delete", new_callable=AsyncMock, return_value=0):
                await qs.delete()
                mock_check.assert_any_call(SampleModel, "delete", ignore_permissions=True)

@pytest.mark.asyncio
async def test_queryset_permission_error_returns_empty():
    qs = SampleModel.objects.all()
    with patch("openviper.db.models.check_permission_for_model", side_effect=ModelPermissionError("denied")):
        assert await qs.all() == []
        assert await qs.count() == 0

@pytest.mark.asyncio
async def test_queryset_last_no_order(setup_db):
    # Ensure table exists first if not using setup_db, but we are using it.
    mgr = SampleModel.objects
    # last() on unordered queryset should use -id
    with patch("openviper.db.models.execute_select", new_callable=AsyncMock) as mock_select:
        mock_row = MagicMock()
        mock_select.return_value = [mock_row]
        res = await mgr.filter(ignore_permissions=True).last()
        assert res is not None
        # Should have called without any special ordering in qs_arg
        qs_arg = mock_select.call_args[0][0]
        assert qs_arg._order == []

def test_model_content_type():
    obj = SampleModel(name="test")
    # Manually setting them since they aren't auto-set without proper meta/registry setup
    obj._app_name = "myapp"
    obj._model_name = "Sample"
    assert obj.content_type == "myapp.Sample"
    SampleModel._app_name = "myapp"
    SampleModel._model_name = "Sample"
    assert SampleModel.get_content_type_label() == "myapp.Sample"

@pytest.mark.asyncio
async def test_manager_get_or_create():
    mgr = SampleModel.objects
    with patch.object(mgr, "get") as mock_get:
        mock_get.side_effect = DoesNotExist()
        with patch.object(mgr, "create") as mock_create:
            mock_create.return_value = SampleModel(id=1, name="new")
            obj, created = await mgr.get_or_create(name="new")
            assert created is True
            assert obj.id == 1


@pytest.mark.asyncio
async def test_model_aiter(setup_db):
    with patch("openviper.db.models.execute_select", new_callable=AsyncMock, return_value=[]):
        async for _ in SampleModel.objects.all():
            pass


@pytest.mark.asyncio
async def test_model_get(setup_db):
    with patch("openviper.db.models.execute_select", new_callable=AsyncMock, return_value=[]):
        res = await SampleModel.objects.get_or_none(id=1)
        assert res is None
