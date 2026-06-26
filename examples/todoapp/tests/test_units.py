"""Unit tests - models, settings, admin registrations, helpers, startup."""

from __future__ import annotations

from unittest.mock import MagicMock

from admin import TodoAdmin, UserAdmin
from app import is_authenticated_request, redirect_to_login, startup
from models import Todo

from openviper.auth import get_user_model
from openviper.conf import settings


class TestTodoModel:
    def test_str_returns_title(self):
        assert str(Todo(title="Buy milk", done=False, owner_id=1)) == "Buy milk"

    def test_str_empty_title(self):
        assert str(Todo(title=None, done=False, owner_id=1)) == ""

    async def test_save_and_query(self, user):
        await Todo(title="Task A", done=False, owner_id=user.id).save()
        todos = await Todo.objects.filter(owner_id=user.id).all()
        assert len(todos) == 1
        assert todos[0].title == "Task A"
        assert todos[0].done is False


class TestMiniAppSettings:
    def test_project_name(self):
        assert settings.PROJECT_NAME == "miniapp"

    def test_database_url_set(self):
        url = settings.DATABASES["default"]["OPTIONS"]["URL"]
        assert "sqlite" in url

    def test_installed_apps(self):
        assert "openviper.auth" in settings.INSTALLED_APPS
        assert "openviper.admin" in settings.INSTALLED_APPS

    def test_middleware_contains_auth_and_admin(self):
        mw = " ".join(settings.MIDDLEWARE)
        assert "AuthenticationMiddleware" in mw
        assert "AdminMiddleware" in mw

    def test_session_fields(self):
        assert settings.SESSION_COOKIE_NAME == "sessionid"
        assert settings.SESSION_TIMEOUT.total_seconds() > 0


class TestAdminRegistrations:
    def test_user_admin_attributes(self):
        assert "username" in UserAdmin.search_fields
        assert "email" in UserAdmin.search_fields
        assert "is_active" in UserAdmin.list_filter
        assert "password" in UserAdmin.exclude
        assert "created_at" in UserAdmin.readonly_fields

    def test_todo_admin_attributes(self):
        assert "done" in TodoAdmin.list_filter
        assert "title" in TodoAdmin.search_fields
        assert "created_at" in TodoAdmin.readonly_fields
        assert "id" in TodoAdmin.list_display


class TestHelpers:
    def test_is_authenticated_true(self):
        req = MagicMock()
        req.user.is_authenticated = True
        assert is_authenticated_request(req) is True

    def test_is_authenticated_false(self):
        req = MagicMock()
        req.user.is_authenticated = False
        assert is_authenticated_request(req) is False

    def test_is_authenticated_no_attribute(self):
        class TestUser:
            pass

        class TestRequest:
            user = TestUser()

        assert is_authenticated_request(TestRequest()) is False

    def test_redirect_to_login_default(self):
        resp = redirect_to_login()
        assert resp.status_code == 303
        location = resp.headers["location"]
        assert "/login" in location
        assert "next=" in location
        assert "todos" in location

    def test_redirect_to_login_custom_next(self):
        resp = redirect_to_login("/custom")
        assert "/custom" in resp.headers["location"]


class TestStartup:
    async def test_creates_demo_user(self):
        """startup() creates a demo user when none exists."""
        user_model = get_user_model()
        await startup()

        demo = await user_model.objects.get_or_none(username="demo")
        assert demo is not None
        assert demo.email == "demo@example.com"

    async def test_skips_existing_demo_user(self):
        """startup() is idempotent - no duplicate if demo user exists."""
        user_model = get_user_model()
        user = user_model(username="demo", email="demo@example.com")
        await user.set_password("demo1234")
        await user.save()

        await startup()  # must not raise

        results = await user_model.objects.filter(username="demo").all()
        assert len(results) == 1
