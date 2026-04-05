from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.db.fields import CharField, IntegerField
from openviper.db.models import Model


class MockModel(Model):
    id = IntegerField(primary_key=True, auto_increment=True)
    name = CharField()


@pytest.mark.asyncio
async def test_on_change_receives_change_dict_on_update():
    instance = MockModel(id=1, name="Original")
    instance._previous_state = {"id": 1, "name": "Original"}
    instance._persisted = True
    instance.name = "Changed"

    # Mock dispatcher
    mock_dispatcher = MagicMock()

    with patch("openviper.db.events.get_dispatcher", return_value=mock_dispatcher):
        with patch("openviper.db.models.execute_save", new=AsyncMock()):
            await instance.save()

            # Verify trigger called for on_change with change_dict
            # triggers: before_validate, validate, before_save, on_update, on_change
            calls = [call.args for call in mock_dispatcher.trigger.call_args_list]
            on_change_calls = [c for c in calls if c[1] == "on_change"]

            assert len(on_change_calls) == 1
            args = on_change_calls[0]
            assert args[1] == "on_change"
            assert args[2] == instance

            # Since trigger now takes **kwargs, we check call_args.kwargs
            for call in mock_dispatcher.trigger.call_args_list:
                if call.args[1] == "on_change":
                    assert "change_dict" in call.kwargs
                    assert call.kwargs["change_dict"] == {"name": "Original"}


@pytest.mark.asyncio
async def test_on_change_fires_on_create():
    instance = MockModel(name="New")

    # Mock dispatcher
    mock_dispatcher = MagicMock()

    with patch("openviper.db.events.get_dispatcher", return_value=mock_dispatcher):
        with patch("openviper.db.models.execute_save", new=AsyncMock()):
            # Simulate ID being set during save
            async def side_effect(inst, **kwargs):
                inst.id = 1

            with patch("openviper.db.models.execute_save", side_effect=side_effect):
                await instance.save()

            on_change_calls = [
                c for c in mock_dispatcher.trigger.call_args_list if c.args[1] == "on_change"
            ]
            assert len(on_change_calls) == 1

            call = on_change_calls[0]
            assert "change_dict" in call.kwargs
            # On create, all fields are treated as changed
            assert call.kwargs["change_dict"]["name"] == "New"
            assert call.kwargs["change_dict"]["id"] == 1
