"""Unit tests — models, settings, admin registrations, helpers, startup."""

from __future__ import annotations

from unittest.mock import MagicMock

# ── Todo model ───────────────────────────────────────────────────────────────


class TestTodoModel:
    def test_str_returns_title(self):
        from models import Todo

        assert str(Todo(title="Buy milk", done=False, owner_id=1)) == "Buy milk"

    def test_str_empty_title(self):
        from models import Todo

        assert str(Todo(title=None, done=False, owner_id=1)) == ""

    async def test_save_and_query(self, user):
        from models import Todo

        await Todo(title="Task A", done=False, owner_id=user.id).save()
        todos = await Todo.objects.filter(owner_id=user.id).all()
        assert len(todos) == 1
        assert todos[0].title == "Task A"
        assert todos[0].done is False


# ── Settings ─────────────────────────────────────────────────────────────────


class TestMiniAppSettings:
    def test_project_name(self):
        from openviper.conf import settings

        assert settings.PROJECT_NAME == "miniapp"

    def test_database_url_set(self):
        from openviper.conf import settings

        assert "sqlite" in settings.DATABASE_URL

    def test_installed_apps(self):
        from openviper.conf import settings

        assert "openviper.auth" in settings.INSTALLED_APPS
        assert "openviper.admin" in settings.INSTALLED_APPS

    def test_middleware_contains_auth_and_admin(self):
        from openviper.conf import settings

        mw = " ".join(settings.MIDDLEWARE)
        assert "AuthenticationMiddleware" in mw
        assert "AdminMiddleware" in mw

    def test_session_fields(self):
        from openviper.conf import settings

        assert settings.SESSION_COOKIE_NAME == "sessionid"
        assert settings.SESSION_TIMEOUT.total_seconds() > 0


# ── Admin registrations ───────────────────────────────────────────────────────


class TestAdminRegistrations:
    def test_user_admin_attributes(self):
        from admin import UserAdmin

        assert "username" in UserAdmin.search_fields
        assert "email" in UserAdmin.search_fields
        assert "is_active" in UserAdmin.list_filter
        assert "password" in UserAdmin.exclude
        assert "created_at" in UserAdmin.readonly_fields

    def test_todo_admin_attributes(self):
        from admin import TodoAdmin

        assert "done" in TodoAdmin.list_filter
        assert "title" in TodoAdmin.search_fields
        assert "created_at" in TodoAdmin.readonly_fields
        assert "id" in TodoAdmin.list_display


# ── App helpers ───────────────────────────────────────────────────────────────


class TestHelpers:
    def test_is_authenticated_true(self):
        from app import _is_authenticated

        req = MagicMock()
        req.user.is_authenticated = True
        assert _is_authenticated(req) is True

    def test_is_authenticated_false(self):
        from app import _is_authenticated

        req = MagicMock()
        req.user.is_authenticated = False
        assert _is_authenticated(req) is False

    def test_is_authenticated_no_attribute(self):
        from app import _is_authenticated

        class _User:
            pass

        class _Request:
            user = _User()

        assert _is_authenticated(_Request()) is False

    def test_redirect_to_login_default(self):
        from app import _redirect_to_login

        resp = _redirect_to_login()
        assert resp.status_code == 303
        location = resp.headers["location"]
        assert "/login" in location
        assert "next=" in location
        assert "todos" in location

    def test_redirect_to_login_custom_next(self):
        from app import _redirect_to_login

        resp = _redirect_to_login("/custom")
        assert "/custom" in resp.headers["location"]


# ── Startup function ──────────────────────────────────────────────────────────


class TestStartup:
    async def test_creates_demo_user(self):
        """startup() creates a demo user when none exists."""
        from app import startup

        from openviper.auth import get_user_model

        User = get_user_model()  # noqa: N806
        await startup()

        demo = await User.objects.get_or_none(username="demo")
        assert demo is not None
        assert demo.email == "demo@example.com"

    async def test_skips_existing_demo_user(self):
        """startup() is idempotent — no duplicate if demo user exists."""
        from app import startup

        from openviper.auth import get_user_model

        User = get_user_model()  # noqa: N806
        u = User(username="demo", email="demo@example.com")
        u.set_password("demo1234")
        await u.save()

        await startup()  # must not raise

        results = await User.objects.filter(username="demo").all()
        assert len(results) == 1
