"""
Tests for admin registry
"""

import pytest

from openviper.admin import admin as admin1
from openviper.admin.options import ModelAdmin
from openviper.admin.registry import AdminRegistry, admin as admin2


class MockModel:
    """Mock model for testing"""

    __name__ = "MockModel"

    class Meta:
        app_label = "testapp"
        verbose_name = "Mock Model"
        verbose_name_plural = "Mock Models"


class CustomModelAdmin(ModelAdmin):
    """Custom ModelAdmin for testing"""

    list_display = ["id", "name"]
    list_filter = ["status"]
    search_fields = ["name"]


class TestAdminRegistry:
    """Tests for AdminRegistry class"""

    def test_singleton_instance(self):
        """Test that admin is a singleton"""

        assert admin1 is admin2

    def test_register_model_with_default_admin(self):
        """Test registering a model with default ModelAdmin"""
        registry = AdminRegistry()
        registry.register(MockModel)

        assert MockModel in registry._registry
        admin_class = registry._registry[MockModel]
        assert isinstance(admin_class, ModelAdmin)

    def test_register_model_with_custom_admin(self):
        """Test registering a model with custom ModelAdmin"""
        registry = AdminRegistry()
        registry.register(MockModel, CustomModelAdmin)

        assert MockModel in registry._registry
        admin_instance = registry._registry[MockModel]
        assert admin_instance.list_display == ["id", "name"]

    def test_register_already_registered_raises(self):
        """Test that registering same model twice raises error"""
        registry = AdminRegistry()
        registry.register(MockModel)

        with pytest.raises(ValueError, match="already registered"):
            registry.register(MockModel)

    def test_unregister_model(self):
        """Test unregistering a model"""
        registry = AdminRegistry()
        registry.register(MockModel)
        registry.unregister(MockModel)

        assert MockModel not in registry._registry

    def test_unregister_not_registered_raises(self):
        """Test that unregistering non-registered model raises error"""
        registry = AdminRegistry()

        with pytest.raises(ValueError, match="not registered"):
            registry.unregister(MockModel)

    def test_is_registered(self):
        """Test is_registered method"""
        registry = AdminRegistry()

        assert not registry.is_registered(MockModel)
        registry.register(MockModel)
        assert registry.is_registered(MockModel)

    def test_get_model_admin(self):
        """Test get_model_admin method"""
        registry = AdminRegistry()
        registry.register(MockModel, CustomModelAdmin)

        admin_instance = registry.get_model_admin(MockModel)
        assert admin_instance is not None
        assert admin_instance.list_display == ["id", "name"]

    def test_get_model_admin_not_registered(self):
        """Test get_model_admin returns None for non-registered model"""
        registry = AdminRegistry()

        assert registry.get_model_admin(MockModel) is None

    def test_get_registered_models(self):
        """Test get_registered_models method"""
        registry = AdminRegistry()

        class AnotherModel:
            __name__ = "AnotherModel"

            class Meta:
                app_label = "testapp"

        registry.register(MockModel)
        registry.register(AnotherModel)

        models = registry.get_registered_models()
        assert MockModel in models
        assert AnotherModel in models

    def test_get_app_label(self):
        """Test _get_app_label method"""
        registry = AdminRegistry()

        label = registry._get_app_label(MockModel)
        assert label == "testapp"

    def test_get_model_name(self):
        """Test _get_model_name method"""
        registry = AdminRegistry()

        name = registry._get_model_name(MockModel)
        assert name == "mockmodel"

    def test_get_model_by_label_and_name(self):
        """Test get_model_by_label_and_name method"""
        registry = AdminRegistry()
        registry.register(MockModel)

        model = registry.get_model_by_label_and_name("testapp", "mockmodel")
        assert model is MockModel

    def test_get_model_by_label_and_name_not_found(self):
        """Test get_model_by_label_and_name returns None when not found"""
        registry = AdminRegistry()

        model = registry.get_model_by_label_and_name("testapp", "nonexistent")
        assert model is None


class TestAdminRegistryConfig:
    """Tests for AdminRegistry model config generation"""

    def test_get_model_config(self):
        """Test get_model_config generates correct config"""
        registry = AdminRegistry()
        registry.register(MockModel, CustomModelAdmin)

        config = registry.get_model_config(MockModel)

        assert config["app_label"] == "testapp"
        assert config["model_name"] == "mockmodel"
        assert config["list_display"] == ["id", "name"]
        assert config["list_filter"] == ["status"]
        assert config["search_fields"] == ["name"]

    def test_get_all_model_configs(self):
        """Test get_all_model_configs returns configs for all models"""
        registry = AdminRegistry()
        registry.register(MockModel)

        configs = registry.get_all_model_configs()

        assert len(configs) == 1
        assert configs[0]["model_name"] == "mockmodel"

    def test_register_decorator_usage(self):
        registry = AdminRegistry()
        decorator = registry.register(MockModel)
        assert callable(decorator)
        decorator(CustomModelAdmin)
        assert isinstance(registry.get_model_admin(MockModel), CustomModelAdmin)

    def test_get_model_admin_by_name(self):
        registry = AdminRegistry()
        registry.register(MockModel, CustomModelAdmin)
        assert isinstance(registry.get_model_admin_by_name("mockmodel"), CustomModelAdmin)
        assert isinstance(registry.get_model_admin_by_name("MockModel"), CustomModelAdmin)
        with pytest.raises(ValueError, match="No model named"):
            registry.get_model_admin_by_name("invalid")

    def test_get_model_by_name(self):
        registry = AdminRegistry()
        registry.register(MockModel)
        assert registry.get_model_by_name("mockmodel") is MockModel
        with pytest.raises(ValueError, match="No model named"):
            registry.get_model_by_name("invalid")

    def test_get_all_models(self):
        registry = AdminRegistry()
        registry.register(MockModel)
        models = registry.get_all_models()
        assert len(models) == 1
        assert models[0][0] is MockModel

    def test_discover_from_app(self):
        registry = AdminRegistry()
        from unittest.mock import patch

        with patch("importlib.import_module") as mock_import:
            registry.discover_from_app("test_app")
            mock_import.assert_called_with("test_app.admin")

            mock_import.side_effect = ImportError("test")
            registry.discover_from_app("test_app_fail")

    def test_auto_discover_from_installed_apps(self):
        registry = AdminRegistry()
        from unittest.mock import MagicMock, patch

        with patch("openviper.admin.registry.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = ["app1", "app2"]
            with patch.object(registry, "discover_from_app") as mock_discover:
                registry.auto_discover_from_installed_apps()
                assert mock_discover.call_count == 2
                assert registry._discovered is True

                # calling again does nothing
                registry.auto_discover_from_installed_apps()
                assert mock_discover.call_count == 2

    def test_get_models_grouped_by_app(self):
        registry = AdminRegistry()
        registry.register(MockModel)

        groups = registry.get_models_grouped_by_app()
        assert "testapp" in groups
        assert len(groups["testapp"]) == 1
        assert groups["testapp"][0][0] is MockModel

    def test_get_model_admin_by_app_and_name(self):
        registry = AdminRegistry()
        registry.register(MockModel, CustomModelAdmin)

        assert isinstance(
            registry.get_model_admin_by_app_and_name("testapp", "mockmodel"), CustomModelAdmin
        )
        # fallback by name
        assert isinstance(
            registry.get_model_admin_by_app_and_name("wrongapp", "mockmodel"), CustomModelAdmin
        )

    def test_get_model_by_app_and_name(self):
        registry = AdminRegistry()
        registry.register(MockModel)

        assert registry.get_model_by_app_and_name("testapp", "mockmodel") is MockModel
        assert registry.get_model_by_app_and_name("wrongapp", "mockmodel") is MockModel

    def test_get_app_label_fallback(self):
        registry = AdminRegistry()

        class NoMetaModel:
            _app_name = "fallback_app"

        assert registry._get_app_label(NoMetaModel) == "fallback_app"

    def test_get_model_config_no_admin(self):
        registry = AdminRegistry()

        class UntrackedModel:
            pass

        assert registry.get_model_config(UntrackedModel) == {}

    def test_clear(self):
        registry = AdminRegistry()
        registry.register(MockModel)
        registry._discovered = True

        registry.clear()
        assert len(registry._registry) == 0
        assert registry._discovered is False
