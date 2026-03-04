import pytest

from openviper.admin.decorators import register
from openviper.admin.options import ModelAdmin
from openviper.admin.registry import AdminRegistry
from openviper.db.fields import IntegerField
from openviper.db.models import Model


class DummyModel(Model):
    id = IntegerField(primary_key=True)


class AnotherModel(Model):
    id = IntegerField(primary_key=True)


def test_register_decorator():
    # It uses the global admin registry, let's clear it first to avoid pollution
    import contextlib

    from openviper.admin.registry import NotRegistered, admin

    with contextlib.suppress(NotRegistered):
        admin.unregister(DummyModel)
    with contextlib.suppress(NotRegistered):
        admin.unregister(AnotherModel)

    @register(DummyModel, AnotherModel)
    class DummyAdmin(ModelAdmin):
        pass

    assert admin.is_registered(DummyModel)
    assert admin.is_registered(AnotherModel)
    assert isinstance(admin.get_model_admin(DummyModel), DummyAdmin)
    assert isinstance(admin.get_model_admin(AnotherModel), DummyAdmin)

    # Cleanup
    with contextlib.suppress(NotRegistered):
        admin.unregister(DummyModel)
    with contextlib.suppress(NotRegistered):
        admin.unregister(AnotherModel)
