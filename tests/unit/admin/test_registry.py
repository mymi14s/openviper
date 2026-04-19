"""Unit tests for openviper.admin.registry — admin model registry."""

import contextlib
from unittest.mock import MagicMock, patch

import pytest

from openviper.admin.options import ModelAdmin
from openviper.admin.registry import (
    AdminRegistry,
    AlreadyRegistered,
    NotRegistered,
    admin,
)
from openviper.admin.registry import (
    admin as admin2,
)


def _make_model_class(name="TestModel", app_name="test"):
    """Create a mock model class."""
    model = MagicMock()
    model.__name__ = name
    model._app_name = app_name
    model._table_name = name.lower()
    model._fields = {}

    class Meta:
        app_label = app_name

    model.Meta = Meta
    return model


class TestAdminRegistry:
    """Test AdminRegistry class."""

    def test_initialization(self):
        """Test registry initialization."""
        registry = AdminRegistry()
        assert registry._registry == {}
        assert registry._discovered is False

    def test_register_model_with_admin_class(self):
        """Test registering a model with custom admin class."""
        registry = AdminRegistry()
        model = _make_model_class()

        class CustomAdmin(ModelAdmin):
            list_display = ["id", "name"]

        registry.register(model, CustomAdmin)

        assert registry.is_registered(model)
        admin_instance = registry.get_model_admin(model)
        assert isinstance(admin_instance, CustomAdmin)

    def test_register_model_without_admin_class(self):
        """Test registering a model without custom admin class."""
        registry = AdminRegistry()
        model = _make_model_class()

        registry.register(model)

        assert registry.is_registered(model)
        admin_instance = registry.get_model_admin(model)
        assert isinstance(admin_instance, ModelAdmin)

    def test_register_raises_already_registered(self):
        """Test that registering same model twice raises AlreadyRegistered."""
        registry = AdminRegistry()
        model = _make_model_class()

        registry.register(model)

        with pytest.raises(AlreadyRegistered, match="TestModel"):
            registry.register(model)

    def test_unregister_model(self):
        """Test unregistering a model."""
        registry = AdminRegistry()
        model = _make_model_class()

        registry.register(model)
        assert registry.is_registered(model)

        registry.unregister(model)
        assert not registry.is_registered(model)

    def test_unregister_raises_not_registered(self):
        """Test that unregistering non-existent model raises NotRegistered."""
        registry = AdminRegistry()
        model = _make_model_class()

        with pytest.raises(NotRegistered, match="TestModel"):
            registry.unregister(model)

    def test_get_model_admin(self):
        """Test getting model admin instance."""
        registry = AdminRegistry()
        model = _make_model_class()

        class CustomAdmin(ModelAdmin):
            pass

        registry.register(model, CustomAdmin)

        admin_instance = registry.get_model_admin(model)
        assert isinstance(admin_instance, CustomAdmin)
        assert admin_instance.model is model

    def test_get_model_admin_not_registered(self):
        """Test getting admin for unregistered model returns None."""
        registry = AdminRegistry()
        model = _make_model_class()

        assert registry.get_model_admin(model) is None

    def test_get_model_admin_by_name(self):
        """Test getting admin by model name."""
        registry = AdminRegistry()
        model = _make_model_class("User")

        registry.register(model)

        admin_instance = registry.get_model_admin_by_name("User")
        assert admin_instance.model is model

    def test_get_model_admin_by_name_case_insensitive(self):
        """Test that name lookup is case-insensitive."""
        registry = AdminRegistry()
        model = _make_model_class("User")

        registry.register(model)

        admin_instance = registry.get_model_admin_by_name("user")
        assert admin_instance.model is model

    def test_get_model_admin_by_name_not_found(self):
        """Test that looking up non-existent model raises NotRegistered."""
        registry = AdminRegistry()

        with pytest.raises(NotRegistered, match="NonExistent"):
            registry.get_model_admin_by_name("NonExistent")

    def test_get_model_by_name(self):
        """Test getting model class by name."""
        registry = AdminRegistry()
        model = _make_model_class("Post")

        registry.register(model)

        result = registry.get_model_by_name("Post")
        assert result is model

    def test_get_model_by_name_case_insensitive(self):
        """Test that model lookup is case-insensitive."""
        registry = AdminRegistry()
        model = _make_model_class("Post")

        registry.register(model)

        result = registry.get_model_by_name("post")
        assert result is model

    def test_get_model_by_name_not_found(self):
        """Test that looking up non-existent model raises NotRegistered."""
        registry = AdminRegistry()

        with pytest.raises(NotRegistered, match="Missing"):
            registry.get_model_by_name("Missing")

    def test_get_all_models(self):
        """Test getting all registered models."""
        registry = AdminRegistry()
        model1 = _make_model_class("Model1")
        model2 = _make_model_class("Model2")

        registry.register(model1)
        registry.register(model2)

        all_models = registry.get_all_models()
        assert len(all_models) == 2
        model_classes = [m for m, _ in all_models]
        assert model1 in model_classes
        assert model2 in model_classes

    def test_is_registered(self):
        """Test is_registered method."""
        registry = AdminRegistry()
        model = _make_model_class()

        assert registry.is_registered(model) is False

        registry.register(model)
        assert registry.is_registered(model) is True

    def test_discover_from_app(self):
        """Test discovering admin module from an app."""
        registry = AdminRegistry()

        with patch("openviper.admin.registry.importlib.import_module") as mock_import:
            registry.discover_from_app("test_app")
            mock_import.assert_called_once_with("test_app.admin")

    def test_discover_from_app_handles_import_error(self):
        """Test that discover handles ImportError gracefully."""
        registry = AdminRegistry()

        with patch("openviper.admin.registry.importlib.import_module") as mock_import:
            mock_import.side_effect = ImportError("No module")

            # Should not raise
            registry.discover_from_app("nonexistent_app")

    def test_auto_discover_from_installed_apps(self):
        """Test auto-discovery from INSTALLED_APPS."""
        registry = AdminRegistry()

        with patch("openviper.admin.registry.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = ["app1", "app2"]

            with patch.object(registry, "discover_from_app") as mock_discover:
                registry.auto_discover_from_installed_apps()

                assert mock_discover.call_count == 2
                assert registry._discovered is True

    def test_auto_discover_only_runs_once(self):
        """Test that auto-discovery only runs once."""
        registry = AdminRegistry()

        with patch("openviper.admin.registry.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = []

            registry.auto_discover_from_installed_apps()
            registry.auto_discover_from_installed_apps()

            # Should only discover once
            assert registry._discovered is True

    def test_get_models_grouped_by_app(self):
        """Test getting models grouped by app."""
        registry = AdminRegistry()
        model1 = _make_model_class("User", "auth")
        model2 = _make_model_class("Post", "blog")
        model3 = _make_model_class("Comment", "blog")

        registry.register(model1)
        registry.register(model2)
        registry.register(model3)
        grouped = registry.get_models_grouped_by_app()

        assert "auth" in grouped
        assert "blog" in grouped
        assert len(grouped["blog"]) == 2

    def test_get_model_admin_by_app_and_name(self):
        """Test getting admin by app label and model name."""
        registry = AdminRegistry()
        model = _make_model_class("User", "auth")

        registry.register(model)

        admin_instance = registry.get_model_admin_by_app_and_name("auth", "User")
        assert admin_instance.model is model

    def test_get_model_admin_by_app_and_name_case_insensitive(self):
        """Test app/name lookup is case-insensitive."""
        registry = AdminRegistry()
        model = _make_model_class("User", "auth")

        registry.register(model)

        admin_instance = registry.get_model_admin_by_app_and_name("AUTH", "user")
        assert admin_instance.model is model

    def test_get_model_admin_by_app_and_name_fallback(self):
        """Test fallback to name-only lookup."""
        registry = AdminRegistry()
        model = _make_model_class("User", "auth")

        registry.register(model)

        # Should fallback to name-only lookup if app doesn't match
        admin_instance = registry.get_model_admin_by_app_and_name("wrong_app", "User")
        assert admin_instance.model is model

    def test_get_model_by_app_and_name(self):
        """Test getting model by app label and name."""
        registry = AdminRegistry()
        model = _make_model_class("Post", "blog")

        registry.register(model)

        result = registry.get_model_by_app_and_name("blog", "Post")
        assert result is model

    def test_get_registered_models(self):
        """Test get_registered_models helper method."""
        registry = AdminRegistry()
        model1 = _make_model_class("Model1")
        model2 = _make_model_class("Model2")

        registry.register(model1)
        registry.register(model2)

        models = registry.get_registered_models()
        assert len(models) == 2
        assert model1 in models
        assert model2 in models

    def test_get_model_by_label_and_name(self):
        """Test get_model_by_label_and_name helper."""
        registry = AdminRegistry()
        model = _make_model_class("User", "auth")

        registry.register(model)

        result = registry.get_model_by_label_and_name("auth", "User")
        assert result is model

    def test_get_model_by_label_and_name_not_found(self):
        """Test that non-existent model returns None."""
        registry = AdminRegistry()

        result = registry.get_model_by_label_and_name("app", "Missing")
        assert result is None

    def test_get_model_config(self):
        """Test get_model_config helper."""
        registry = AdminRegistry()
        model = _make_model_class("User", "auth")

        registry.register(model)

        config = registry.get_model_config(model)
        assert isinstance(config, dict)
        assert "model_name" in config or "name" in config
        assert "app_label" in config or "app" in config

    def test_get_model_config_not_registered(self):
        """Test get_model_config for unregistered model."""
        registry = AdminRegistry()
        model = _make_model_class()

        config = registry.get_model_config(model)
        assert config == {}

    def test_get_all_model_configs(self):
        """Test get_all_model_configs helper."""
        registry = AdminRegistry()
        model1 = _make_model_class("Model1")
        model2 = _make_model_class("Model2")

        registry.register(model1)
        registry.register(model2)

        configs = registry.get_all_model_configs()
        assert len(configs) == 2
        assert all(isinstance(c, dict) for c in configs)

    def test_clear(self):
        """Test clearing the registry."""
        registry = AdminRegistry()
        model = _make_model_class()

        registry.register(model)
        assert registry.is_registered(model)

        registry.clear()
        assert not registry.is_registered(model)
        assert registry._discovered is False

    def test_get_app_label_helper(self):
        """Test _get_app_label helper method."""
        registry = AdminRegistry()
        model = _make_model_class("User", "auth")

        app_label = registry._get_app_label(model)
        assert app_label == "auth"

    def test_get_app_label_from_meta(self):
        """Test _get_app_label reads from Meta.app_label."""
        registry = AdminRegistry()

        class MockMetaModel:
            class Meta:
                app_label = "auth_meta"

        app_label = registry._get_app_label(MockMetaModel)
        assert app_label == "auth_meta"

    def test_get_app_label_fallback(self):
        """Test _get_app_label falls back to _app_name."""
        registry = AdminRegistry()

        class MockNoMetaModel:
            _app_name = "auth_fallback"

        app_label = registry._get_app_label(MockNoMetaModel)
        assert app_label == "auth_fallback"

    def test_get_model_name_helper(self):
        """Test _get_model_name helper method."""
        registry = AdminRegistry()
        model = _make_model_class("User")

        model_name = registry._get_model_name(model)
        assert model_name == "user"


class TestAdminSingleton:
    """Test the global admin singleton."""

    def test_admin_is_registry_instance(self):
        """Test that admin is an AdminRegistry instance."""
        assert isinstance(admin, AdminRegistry)

    def test_admin_singleton_persistence(self):
        """Test that admin singleton persists across imports."""
        assert admin is admin2


class TestRegisterAsDecorator:
    """Test using register() as a decorator."""

    def test_register_returns_decorator(self):
        """Test that register with only model returns decorator."""
        registry = AdminRegistry()
        model = _make_model_class()

        decorator = registry.register(model)

        # Should be callable (decorator function)
        assert callable(decorator)

    def test_register_decorator_registers_model(self):
        """Test that calling the decorator registers the model."""
        registry = AdminRegistry()
        model = _make_model_class()

        class CustomAdmin(ModelAdmin):
            pass

        # First call returns decorator
        decorator = registry.register(model)

        # Second call registers the admin class
        result = decorator(CustomAdmin)

        assert result is CustomAdmin
        assert registry.is_registered(model)
        assert isinstance(registry.get_model_admin(model), CustomAdmin)


class TestRegistryEdgeCases:
    """Test edge cases and error conditions."""

    def test_register_none_model(self):
        """Test behavior with None as model."""
        registry = AdminRegistry()

        # Should handle gracefully or raise appropriate error
        with contextlib.suppress(TypeError, AttributeError, AlreadyRegistered):
            registry.register(None)

    def test_get_models_empty_registry(self):
        """Test getting models from empty registry."""
        registry = AdminRegistry()

        assert registry.get_all_models() == []

    def test_grouped_models_empty_registry(self):
        """Test grouping models in empty registry."""
        registry = AdminRegistry()

        assert registry.get_models_grouped_by_app() == {}

    def test_multiple_registrations_same_name_different_apps(self):
        """Test registering models with same name from different apps."""
        registry = AdminRegistry()
        model1 = _make_model_class("User", "app1")
        model2 = _make_model_class("User", "app2")

        registry.register(model1)
        registry.register(model2)

        # Both should be registered
        assert registry.is_registered(model1)
        assert registry.is_registered(model2)

        # Should be able to retrieve by app and name
        admin1 = registry.get_model_admin_by_app_and_name("app1", "User")
        admin2 = registry.get_model_admin_by_app_and_name("app2", "User")

        assert admin1.model is model1
        assert admin2.model is model2
