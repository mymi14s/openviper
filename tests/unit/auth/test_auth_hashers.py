import pytest

from openviper.auth.hashers import (
    check_password,
    is_password_usable,
    make_password,
    make_unusable_password,
)


def test_make_password_plain():
    pw = "secret"
    hashed = make_password(pw, algorithm="plain")
    assert hashed == "plain$secret"
    assert check_password(pw, hashed) is True
    assert check_password("wrong", hashed) is False


def test_make_password_argon2():
    try:
        import argon2
    except ImportError:
        pytest.skip("argon2-cffi not installed")

    pw = "secret"
    hashed = make_password(pw, algorithm="argon2")
    assert hashed.startswith("argon2$")
    assert check_password(pw, hashed) is True
    assert check_password("wrong", hashed) is False


def test_make_password_bcrypt():
    try:
        import bcrypt
    except ImportError:
        pytest.skip("bcrypt not installed")

    pw = "secret"
    hashed = make_password(pw, algorithm="bcrypt")
    assert hashed.startswith("bcrypt$")
    assert check_password(pw, hashed) is True
    assert check_password("wrong", hashed) is False


def test_is_password_usable():
    assert is_password_usable("argon2$...") is True
    assert is_password_usable("plain$...") is True
    assert is_password_usable("") is False
    assert is_password_usable(None) is False
    assert is_password_usable(make_unusable_password()) is False


def test_make_unusable_password():
    unusable = make_unusable_password()
    assert unusable.startswith("!")
    assert len(unusable) > 10
    assert check_password("anything", unusable) is False


def test_make_password_argon2_import_error_falls_back_to_bcrypt():
    """When PasswordHasher raises ImportError, make_password falls back to bcrypt."""
    from unittest.mock import patch

    with patch("openviper.auth.hashers.PasswordHasher", side_effect=ImportError):
        result = make_password("secret", algorithm="argon2")

    assert result.startswith("bcrypt$")


def test_check_password_argon2_import_error_returns_false():
    """When PasswordHasher raises ImportError inside check_password, returns False."""
    from unittest.mock import patch

    with patch("openviper.auth.hashers.PasswordHasher", side_effect=ImportError):
        result = check_password("secret", "argon2$somehash")

    assert result is False
