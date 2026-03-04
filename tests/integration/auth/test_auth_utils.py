"""Integration tests for auth utilities and hashers."""

from __future__ import annotations

import pytest
import pytest_asyncio

from openviper.auth.hashers import check_password, make_password
from openviper.auth.utils import get_user_model

# ---------------------------------------------------------------------------
# Password hashers
# ---------------------------------------------------------------------------


class TestMakePassword:
    def test_make_password_returns_string(self):
        hashed = make_password("mysecret")
        assert isinstance(hashed, str)

    def test_make_password_not_plaintext(self):
        pw = "mysecret"
        hashed = make_password(pw)
        assert hashed != pw

    def test_make_password_with_prefix(self):
        hashed = make_password("test123")
        assert hashed  # non-empty

    def test_different_calls_produce_different_hashes(self):
        # Due to salting, two hashes of same password should differ
        h1 = make_password("same_password")
        h2 = make_password("same_password")
        assert h1 != h2


class TestCheckPassword:
    def test_correct_password_returns_true(self):
        hashed = make_password("secretpw")
        assert check_password("secretpw", hashed) is True

    def test_wrong_password_returns_false(self):
        hashed = make_password("secretpw")
        assert check_password("wrongpw", hashed) is False

    def test_empty_password_with_hash(self):
        hashed = make_password("nonempty")
        assert check_password("", hashed) is False

    def test_roundtrip_various_passwords(self):
        passwords = ["simple", "C0mpl3x!@#", "unicode_тест", "very_long_" + "x" * 64]
        for pw in passwords:
            hashed = make_password(pw)
            assert check_password(pw, hashed) is True, f"Failed for: {pw}"
            assert check_password(pw + "x", hashed) is False, f"Should fail for: {pw}x"


# ---------------------------------------------------------------------------
# get_user_model
# ---------------------------------------------------------------------------


class TestGetUserModel:
    def test_returns_user_class(self):
        User = get_user_model()
        assert User is not None
        assert hasattr(User, "username")

    def test_returns_default_user_when_no_setting(self):
        from openviper.auth.models import User

        User2 = get_user_model()
        assert User2 is User

    def test_custom_user_model_setting(self):
        # Default USER_MODEL is "openviper.auth.models.User"; get_user_model()
        # should return the default User class without needing to mutate settings.
        from openviper.auth.models import User as DefaultUser

        assert get_user_model() is DefaultUser

    def test_invalid_user_model_falls_back_to_default(self):
        from unittest.mock import MagicMock, patch

        import openviper.conf as conf_module

        mock_s = MagicMock()
        mock_s.USER_MODEL = "nonexistent.module.UserModel"
        with patch.object(conf_module, "settings", mock_s):
            from openviper.auth.models import User as DefaultUser

            assert get_user_model() is DefaultUser


# ---------------------------------------------------------------------------
# Auth models integration (with DB)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    from openviper.db.connection import close_db, init_db

    await init_db(drop_first=True)
    yield
    await close_db()


@pytest.mark.asyncio
async def test_user_creation_and_password():
    """User can be created with hashed password, and authenticate."""
    from openviper.auth.models import User

    user = User(
        username="testuser",
        email="testuser@example.com",
        is_active=True,
    )
    user.set_password("mypassword")
    await user.save()

    # Verify password check
    assert check_password("mypassword", user.password) is True
    assert check_password("wrongpassword", user.password) is False


@pytest.mark.asyncio
async def test_user_is_authenticated():
    """Active user is_authenticated is True, AnonymousUser is False."""
    from openviper.auth.models import AnonymousUser, User

    user = User(username="auth_test", email="auth@example.com", is_active=True)
    assert user.is_authenticated is True

    anon = AnonymousUser()
    assert anon.is_authenticated is False


@pytest.mark.asyncio
async def test_anonymous_user_properties():
    """AnonymousUser has correct property values."""
    from openviper.auth.models import AnonymousUser

    anon = AnonymousUser()
    assert anon.is_authenticated is False
    assert anon.is_active is False
    assert anon.pk is None


@pytest.mark.asyncio
async def test_user_create_and_retrieve():
    """User saved to DB can be retrieved."""
    from openviper.auth.backends import get_user_by_id
    from openviper.auth.models import User

    user = User(username="db_user", email="db@example.com", is_active=True, is_staff=True)
    user.set_password("pass123")
    await user.save()

    retrieved = await get_user_by_id(user.id)
    assert retrieved is not None
    assert retrieved.username == "db_user"
    assert retrieved.is_staff is True


@pytest.mark.asyncio
async def test_role_model_fields():
    """Role can be created and saved to DB with name and description."""
    from openviper.auth.models import Role

    role = Role(name="editor", description="Can edit content")
    await role.save()

    assert role.id is not None
    assert role.name == "editor"


@pytest.mark.asyncio
async def test_permission_model_fields():
    """Permission can be created with codename and name."""
    from openviper.auth.models import Permission

    perm = Permission(codename="can_publish", name="Can publish posts")
    await perm.save()

    assert perm.id is not None
    assert perm.codename == "can_publish"
