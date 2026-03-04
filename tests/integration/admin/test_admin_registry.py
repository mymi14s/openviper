import pytest

from openviper.admin.options import ModelAdmin
from openviper.admin.registry import AdminRegistry, AlreadyRegistered, NotRegistered
from openviper.db.models import Model


class MockModel(Model):
    pass


def test_admin_registry_register_unregister():
    registry = AdminRegistry()
    registry.register(MockModel)
    assert registry.is_registered(MockModel)

    with pytest.raises(AlreadyRegistered):
        registry.register(MockModel)

    registry.unregister(MockModel)
    assert not registry.is_registered(MockModel)

    with pytest.raises(NotRegistered):
        registry.unregister(MockModel)


def test_admin_registry_get_model_admin():
    registry = AdminRegistry()
    registry.register(MockModel)
    admin = registry.get_model_admin(MockModel)
    assert isinstance(admin, ModelAdmin)
    assert admin.model == MockModel


def test_admin_registry_get_by_name():
    registry = AdminRegistry()
    registry.register(MockModel)
    assert registry.get_model_by_name("MockModel") == MockModel
    assert registry.get_model_admin_by_name("MockModel").model == MockModel
