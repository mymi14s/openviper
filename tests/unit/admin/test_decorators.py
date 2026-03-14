"""Unit tests for openviper.admin.decorators — @register decorator."""

import pytest

from openviper.admin.decorators import register
from openviper.admin.options import ModelAdmin
from openviper.admin.registry import AlreadyRegistered, admin
from openviper.db.models import Model


class MockModel(Model):
    """Mock model for testing."""

    __name__ = "MockModel"
    _app_name = "test"
    _table_name = "mock_models"
    _fields = {}

    class Meta:
        table_name = "mock_models"


class AnotherMockModel(Model):
    """Another mock model for testing."""

    __name__ = "AnotherMockModel"
    _app_name = "test"
    _table_name = "another_mock_models"
    _fields = {}

    class Meta:
        table_name = "another_mock_models"


class TestRegisterDecorator:
    """Test the @register decorator."""

    def setup_method(self):
        """Clear registry before each test."""
        admin.clear()

    def teardown_method(self):
        """Clear registry after each test."""
        admin.clear()

    def test_register_single_model(self):
        """Test registering a single model."""

        @register(MockModel)
        class MockModelAdmin(ModelAdmin):
            list_display = ["id", "name"]

        assert admin.is_registered(MockModel)
        model_admin = admin.get_model_admin(MockModel)
        assert isinstance(model_admin, MockModelAdmin)

    def test_register_multiple_models(self):
        """Test registering multiple models with the same admin class."""

        @register(MockModel, AnotherMockModel)
        class SharedAdmin(ModelAdmin):
            list_display = ["id"]

        assert admin.is_registered(MockModel)
        assert admin.is_registered(AnotherMockModel)

        mock_admin = admin.get_model_admin(MockModel)
        another_admin = admin.get_model_admin(AnotherMockModel)

        assert isinstance(mock_admin, SharedAdmin)
        assert isinstance(another_admin, SharedAdmin)

    def test_register_returns_admin_class(self):
        """Test that decorator returns the admin class unchanged."""

        @register(MockModel)
        class MockModelAdmin(ModelAdmin):
            list_display = ["id"]

        # The class should still be usable
        assert MockModelAdmin.__name__ == "MockModelAdmin"
        assert hasattr(MockModelAdmin, "list_display")

    def test_register_preserves_admin_class_attributes(self):
        """Test that decorator preserves all admin class attributes."""

        @register(MockModel)
        class CustomAdmin(ModelAdmin):
            list_display = ["id", "name"]
            list_filter = ["status"]
            search_fields = ["name"]

            def custom_method(self):
                return "custom"

        model_admin = admin.get_model_admin(MockModel)
        assert model_admin.list_display == ["id", "name"]
        assert model_admin.list_filter == ["status"]
        assert model_admin.search_fields == ["name"]
        assert hasattr(model_admin, "custom_method")
        assert model_admin.custom_method() == "custom"

    def test_register_with_empty_admin_class(self):
        """Test registering with minimal admin class."""

        @register(MockModel)
        class MinimalAdmin(ModelAdmin):
            pass

        assert admin.is_registered(MockModel)
        model_admin = admin.get_model_admin(MockModel)
        assert isinstance(model_admin, MinimalAdmin)

    def test_register_model_admin_initialization(self):
        """Test that ModelAdmin is properly initialized with the model."""

        @register(MockModel)
        class TestAdmin(ModelAdmin):
            pass

        model_admin = admin.get_model_admin(MockModel)
        assert model_admin.model is MockModel
        assert model_admin._model_name == "MockModel"
        assert model_admin._app_name == "admin"

    def test_register_raises_already_registered(self):
        """Test that registering a model twice raises AlreadyRegistered."""

        @register(MockModel)
        class FirstAdmin(ModelAdmin):
            pass

        # Trying to register the same model again should raise
        with pytest.raises(AlreadyRegistered, match="MockModel"):

            @register(MockModel)
            class SecondAdmin(ModelAdmin):
                pass

    def test_register_different_models_with_same_name(self):
        """Test registering different model classes is fine."""

        class Model1:
            __name__ = "TestModel"
            _app_name = "app1"
            _table_name = "test_model1"
            _fields = {}

        class Model2:
            __name__ = "TestModel"
            _app_name = "app2"
            _table_name = "test_model2"
            _fields = {}

        @register(Model1)
        class Admin1(ModelAdmin):
            pass

        @register(Model2)
        class Admin2(ModelAdmin):
            pass

        assert admin.is_registered(Model1)
        assert admin.is_registered(Model2)
        assert admin.get_model_admin(Model1) is not admin.get_model_admin(Model2)


class TestRegisterDecoratorIntegration:
    """Integration tests for @register decorator with admin registry."""

    def setup_method(self):
        """Clear registry before each test."""
        admin.clear()

    def teardown_method(self):
        """Clear registry after each test."""
        admin.clear()

    def test_decorated_classes_appear_in_registry(self):
        """Test that decorated classes appear in get_all_models."""

        @register(MockModel)
        class MockAdmin(ModelAdmin):
            pass

        @register(AnotherMockModel)
        class AnotherAdmin(ModelAdmin):
            pass

        all_models = admin.get_all_models()
        assert len(all_models) == 2

        model_classes = [m for m, _ in all_models]
        assert MockModel in model_classes
        assert AnotherMockModel in model_classes

    def test_decorator_works_with_registry_methods(self):
        """Test that decorator integrates properly with registry methods."""

        @register(MockModel)
        class MockAdmin(ModelAdmin):
            pass

        # Test get_model_admin_by_name
        model_admin = admin.get_model_admin_by_name("MockModel")
        assert isinstance(model_admin, MockAdmin)

        # Test get_model_by_name
        model = admin.get_model_by_name("MockModel")
        assert model is MockModel

        # Test is_registered
        assert admin.is_registered(MockModel) is True
