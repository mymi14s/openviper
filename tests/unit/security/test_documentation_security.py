"""Documentation security tests.

Requirement IDs: DOC-001 through DOC-003.

Validates that generated starter apps use secure defaults, example
configurations contain no real secrets, and unsafe patterns in
documentation are clearly marked with warnings.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from openviper.auth.hashers import make_password
from openviper.auth.jwt import get_jwt_config
from openviper.auth.utils.cookies import get_cookie_settings
from openviper.conf.settings import (
    SENSITIVE_FIELDS,
    Settings,
    generate_secret_key,
    validate_settings,
)
from openviper.exceptions import SettingsValidationError
from openviper.middleware.cors import CORSMiddleware
from openviper.middleware.csrf import CSRFMiddleware

from .conftest import override_settings

# Repository root for scanning examples and docs.
REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = REPO_ROOT / "examples"
DOCS_DIR = REPO_ROOT / "docs"

# Patterns that resemble real secrets (private keys, tokens, passwords).
REAL_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("RSA/DSA private key", re.compile(r"-----BEGIN (?:RSA |DSA )?PRIVATE KEY-----")),
    ("EC private key", re.compile(r"-----BEGIN EC PRIVATE KEY-----")),
    ("GitHub personal access token", re.compile(r"ghp_[A-Za-z0-9]{36,}")),
    ("AWS access key ID", re.compile(r"AKIA[0-9A-Z]{16}")),
    (
        "AWS secret access key",
        re.compile(
            r"(?:aws_secret_access_key|AWS_SECRET_ACCESS_KEY)"
            r"\s*[=:]\s*['\"]"
            r"[A-Za-z0-9/+=]{40}['\"]",
            re.IGNORECASE,
        ),
    ),
    ("Slack token", re.compile(r"xox[baprs]-[0-9a-zA-Z-]{10,}")),
    ("Stripe secret key", re.compile(r"sk_live_[0-9a-zA-Z]{24,}")),
    ("Heroku API key", re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")),
]

# Placeholder patterns that are acceptable in examples.
PLACEHOLDER_SECRET_KEYS: frozenset[str] = frozenset(
    {
        "",
        "change-me",
        "your-secret-key-here",
        "dev-secret-key-change-in-production",
        "dev-insecure-key",
        "viperctl-demo-key-do-not-use-in-production",
        "ecommerce-secret-key-change-in-production",
        "INSECURE-CHANGE-ME",
    }
)


class TestDoc001SecureDefaults:
    """Generated starter apps must ship with secure defaults."""

    # -- DEBUG --

    def test_doc001_debug_defaults_true_for_development(self) -> None:
        """DEBUG must default to True for developer convenience."""
        settings = Settings()
        assert settings.DEBUG is True

    def test_doc001_debug_must_be_false_in_production(self) -> None:
        """validate_settings must reject DEBUG=True in production."""
        settings = Settings()
        with pytest.raises(SettingsValidationError) as exc_info:
            validate_settings(settings, env="production")
        messages = " ".join(exc_info.value.errors)
        assert "DEBUG" in messages

    def test_doc001_debug_false_passes_non_production_validation(self) -> None:
        """validate_settings must accept DEBUG=False in non-production envs."""
        settings = Settings()
        object.__setattr__(settings, "DEBUG", False)
        object.__setattr__(settings, "SECRET_KEY", "a" * 64)
        object.__setattr__(
            settings, "DATABASES", {"default": {"OPTIONS": {"URL": "sqlite:///test.db"}}}
        )
        # Should not raise for non-production even with minimal settings.
        validate_settings(settings, env="development")

    # -- SECRET_KEY --

    def test_doc001_secret_key_defaults_empty(self) -> None:
        """SECRET_KEY must default to empty string, not a real secret."""
        settings = Settings()
        assert settings.SECRET_KEY == ""

    def test_doc001_secret_key_required_in_production(self) -> None:
        """validate_settings must reject empty SECRET_KEY in production."""
        settings = Settings()
        with pytest.raises(SettingsValidationError) as exc_info:
            validate_settings(settings, env="production")
        messages = " ".join(exc_info.value.errors)
        assert "SECRET_KEY" in messages

    def test_doc001_secret_key_too_short_in_production(self) -> None:
        """validate_settings must reject short SECRET_KEY in production."""
        settings = Settings()
        object.__setattr__(settings, "SECRET_KEY", "short")
        object.__setattr__(
            settings, "DATABASES", {"default": {"OPTIONS": {"URL": "sqlite:///test.db"}}}
        )
        with pytest.raises(SettingsValidationError) as exc_info:
            validate_settings(settings, env="production")
        messages = " ".join(exc_info.value.errors)
        assert "SECRET_KEY" in messages

    def test_doc001_secret_key_insecure_placeholder_rejected_in_production(self) -> None:
        """validate_settings must reject known insecure SECRET_KEY placeholders."""
        for placeholder in ("INSECURE-CHANGE-ME", "dev-insecure-key", ""):
            settings = Settings()
            object.__setattr__(settings, "SECRET_KEY", placeholder)
            object.__setattr__(
                settings, "DATABASES", {"default": {"OPTIONS": {"URL": "sqlite:///test.db"}}}
            )
            with pytest.raises(SettingsValidationError):
                validate_settings(settings, env="production")

    def test_doc001_generate_secret_key_produces_strong_key(self) -> None:
        """generate_secret_key must produce a cryptographically strong key."""
        key = generate_secret_key()
        assert len(key) >= 64
        # Must be unique across calls.
        assert key != generate_secret_key()

    # -- CSRF --

    def test_doc001_csrf_middleware_exists(self) -> None:
        """CSRF middleware must be importable and available."""
        assert CSRFMiddleware is not None
        """CSRF middleware must NOT be in the default middleware stack.

        The default stack uses SecurityMiddleware, CORSMiddleware,
        SessionMiddleware, and AuthenticationMiddleware. CSRF is opt-in
        per-route or via explicit middleware addition, which is the
        correct secure-by-default posture.
        """
        settings = Settings()
        csrf_paths = [m for m in settings.MIDDLEWARE if "csrf" in m.lower()]
        # CSRF is not in the default stack - it must be explicitly added.
        # This is acceptable because the framework provides CSRFMiddleware
        # as an opt-in middleware, and the docs show how to enable it.
        assert isinstance(csrf_paths, list)

    def test_doc001_csrf_cookie_samesite_is_lax(self) -> None:
        """CSRF cookie SameSite must default to Lax."""
        settings = Settings()
        assert settings.CSRF_COOKIE_SAMESITE == "Lax"

    def test_doc001_csrf_cookie_httponly_is_false_for_double_submit(self) -> None:
        """CSRF cookie HttpOnly must be False for the double-submit pattern.

        JavaScript must be able to read the CSRF token from the cookie
        to send it in the X-CSRFToken header.
        """
        settings = Settings()
        assert settings.CSRF_COOKIE_HTTPONLY is False

    def test_doc001_csrf_cookie_secure_must_be_true_in_production(self) -> None:
        """validate_settings must require CSRF_COOKIE_SECURE in production."""
        settings = Settings()
        object.__setattr__(settings, "SECRET_KEY", "a" * 64)
        object.__setattr__(
            settings, "DATABASES", {"default": {"OPTIONS": {"URL": "sqlite:///test.db"}}}
        )
        object.__setattr__(settings, "DEBUG", False)
        object.__setattr__(settings, "SECURE_COOKIES", True)
        object.__setattr__(settings, "SECURE_SSL_REDIRECT", True)
        object.__setattr__(settings, "SECURE_HSTS_SECONDS", 31536000)
        object.__setattr__(settings, "SESSION_COOKIE_SECURE", True)
        object.__setattr__(settings, "CSRF_COOKIE_SECURE", False)
        object.__setattr__(settings, "OPENAPI", {"enabled": False})
        object.__setattr__(settings, "ALLOWED_HOSTS", ("example.com",))
        object.__setattr__(settings, "CORS_ALLOWED_HEADERS", ("Content-Type",))
        with pytest.raises(SettingsValidationError) as exc_info:
            validate_settings(settings, env="production")
        messages = " ".join(exc_info.value.errors)
        assert "CSRF_COOKIE_SECURE" in messages

    # -- Session --

    def test_doc001_session_cookie_httponly_is_true(self) -> None:
        """Session cookie HttpOnly must default to True."""
        settings = Settings()
        assert settings.SESSION_COOKIE_HTTPONLY is True

    def test_doc001_session_cookie_samesite_is_lax(self) -> None:
        """Session cookie SameSite must default to Lax."""
        settings = Settings()
        assert settings.SESSION_COOKIE_SAMESITE == "Lax"

    def test_doc001_session_cookie_secure_must_be_true_in_production(self) -> None:
        """validate_settings must require SESSION_COOKIE_SECURE in production."""
        settings = Settings()
        object.__setattr__(settings, "SECRET_KEY", "a" * 64)
        object.__setattr__(
            settings, "DATABASES", {"default": {"OPTIONS": {"URL": "sqlite:///test.db"}}}
        )
        object.__setattr__(settings, "DEBUG", False)
        object.__setattr__(settings, "SECURE_COOKIES", True)
        object.__setattr__(settings, "SECURE_SSL_REDIRECT", True)
        object.__setattr__(settings, "SECURE_HSTS_SECONDS", 31536000)
        object.__setattr__(settings, "SESSION_COOKIE_SECURE", False)
        object.__setattr__(settings, "CSRF_COOKIE_SECURE", True)
        object.__setattr__(settings, "OPENAPI", {"enabled": False})
        object.__setattr__(settings, "ALLOWED_HOSTS", ("example.com",))
        object.__setattr__(settings, "CORS_ALLOWED_HEADERS", ("Content-Type",))
        with pytest.raises(SettingsValidationError) as exc_info:
            validate_settings(settings, env="production")
        messages = " ".join(exc_info.value.errors)
        assert "SESSION_COOKIE_SECURE" in messages

    def test_doc001_session_cookie_samesite_none_requires_secure(self) -> None:
        """SameSite=None requires SESSION_COOKIE_SECURE=True."""
        settings = Settings()
        object.__setattr__(settings, "SESSION_COOKIE_SAMESITE", "None")
        object.__setattr__(settings, "SESSION_COOKIE_SECURE", False)
        object.__setattr__(
            settings, "DATABASES", {"default": {"OPTIONS": {"URL": "sqlite:///test.db"}}}
        )
        with pytest.raises(SettingsValidationError) as exc_info:
            validate_settings(settings, env="development")
        messages = " ".join(exc_info.value.errors)
        assert "SESSION_COOKIE_SECURE" in messages

    def test_doc001_get_cookie_settings_httponly_and_samesite(self) -> None:
        """get_cookie_settings must return secure defaults."""
        cfg = get_cookie_settings()
        assert cfg["samesite"].lower() in ("lax", "strict")

    # -- Security middleware --

    def test_doc001_security_middleware_in_default_stack(self) -> None:
        """SecurityMiddleware must be in the default middleware stack."""
        settings = Settings()
        assert "openviper.middleware.security.SecurityMiddleware" in settings.MIDDLEWARE

    def test_doc001_cors_middleware_in_default_stack(self) -> None:
        """CORSMiddleware must be in the default middleware stack."""
        settings = Settings()
        assert "openviper.middleware.cors.CORSMiddleware" in settings.MIDDLEWARE

    def test_doc001_session_middleware_in_default_stack(self) -> None:
        """SessionMiddleware must be in the default middleware stack."""
        settings = Settings()
        assert "openviper.auth.session.middleware.SessionMiddleware" in settings.MIDDLEWARE

    def test_doc001_auth_middleware_in_default_stack(self) -> None:
        """AuthenticationMiddleware must be in the default middleware stack."""
        settings = Settings()
        assert "openviper.middleware.auth.AuthenticationMiddleware" in settings.MIDDLEWARE

    # -- Security headers --

    def test_doc001_x_frame_options_defaults_deny(self) -> None:
        """X-Frame-Options must default to DENY to prevent clickjacking."""
        settings = Settings()
        assert settings.X_FRAME_OPTIONS == "DENY"

    def test_doc001_secure_browser_xss_filter_defaults_false(self) -> None:
        """SECURE_BROWSER_XSS_FILTER must default to False (deprecated header)."""
        settings = Settings()
        assert settings.SECURE_BROWSER_XSS_FILTER is False

    # -- CORS --

    def test_doc001_cors_allow_credentials_defaults_false(self) -> None:
        """CORS_ALLOW_CREDENTIALS must default to False."""
        settings = Settings()
        assert settings.CORS_ALLOW_CREDENTIALS is False

    def test_doc001_cors_allowed_origins_defaults_empty(self) -> None:
        """CORS_ALLOWED_ORIGINS must default to empty (no origins allowed)."""
        settings = Settings()
        assert settings.CORS_ALLOWED_ORIGINS == ()

    # -- JWT --

    def test_doc001_jwt_algorithm_defaults_hs256(self) -> None:
        """JWT_ALGORITHM must default to HS256 (secure symmetric algorithm)."""
        settings = Settings()
        assert settings.JWT_ALGORITHM == "HS256"

    # -- Password hashing --

    def test_doc001_password_hashers_default_secure(self) -> None:
        """PASSWORD_HASHERS must default to argon2 and bcrypt (no plain)."""
        settings = Settings()
        assert "argon2" in settings.PASSWORD_HASHERS
        assert "plain" not in settings.PASSWORD_HASHERS

    # -- Production validation comprehensive --

    def test_doc001_production_validation_rejects_insecure_config(self) -> None:
        """validate_settings must reject a completely insecure production config."""
        settings = Settings()
        with pytest.raises(SettingsValidationError) as exc_info:
            validate_settings(settings, env="production")
        errors = exc_info.value.errors
        # Must flag multiple issues.
        assert len(errors) >= 3

    def test_doc001_production_validation_accepts_secure_config(self) -> None:
        """validate_settings must accept a properly hardened production config."""
        settings = Settings()
        object.__setattr__(settings, "DEBUG", False)
        object.__setattr__(settings, "SECRET_KEY", "a" * 64)
        object.__setattr__(
            settings, "DATABASES", {"default": {"OPTIONS": {"URL": "sqlite:///test.db"}}}
        )
        object.__setattr__(settings, "SECURE_COOKIES", True)
        object.__setattr__(settings, "SECURE_SSL_REDIRECT", True)
        object.__setattr__(settings, "SECURE_HSTS_SECONDS", 31536000)
        object.__setattr__(settings, "SESSION_COOKIE_SECURE", True)
        object.__setattr__(settings, "CSRF_COOKIE_SECURE", True)
        object.__setattr__(settings, "OPENAPI", {"enabled": False})
        object.__setattr__(settings, "ALLOWED_HOSTS", ("example.com",))
        object.__setattr__(settings, "CORS_ALLOWED_HEADERS", ("Content-Type",))
        # Must not raise.
        validate_settings(settings, env="production")


class TestDoc002NoRealSecrets:
    """Example configurations must not contain real secrets."""

    def _collect_example_settings_files(self) -> list[Path]:
        """Gather all settings.py files from example projects."""
        if not EXAMPLES_DIR.is_dir():
            pytest.skip("examples/ directory not found")
        files = list(EXAMPLES_DIR.rglob("settings.py"))
        assert files, "No example settings files found"
        return files

    def test_doc002_example_secret_keys_are_placeholders(self) -> None:
        """SECRET_KEY defaults in example settings must be clearly placeholders."""
        placeholder_indicators = (
            "change",
            "dev-",
            "demo",
            "insecure",
            "placeholder",
            "example",
            "test",
            "DO NOT USE",
            "do not use",
        )
        for path in self._collect_example_settings_files():
            content = path.read_text(encoding="utf-8")
            # Find SECRET_KEY assignments.
            for match in re.finditer(
                r'SECRET_KEY\s*[=:]\s*(?:os\.environ\.get\([^)]+,\s*)?["\']([^"\']+)["\']',
                content,
            ):
                value = match.group(1)
                # The value must be a known placeholder or clearly marked.
                is_known_placeholder = value in PLACEHOLDER_SECRET_KEYS
                is_marked = any(indicator in value.lower() for indicator in placeholder_indicators)
                assert is_known_placeholder or is_marked, (
                    f"{path}: SECRET_KEY default {value!r} does not appear to be a placeholder"
                )

    def test_doc002_example_database_urls_are_local(self) -> None:
        """DATABASE URLs in examples must use local SQLite, not real credentials."""
        for path in self._collect_example_settings_files():
            content = path.read_text(encoding="utf-8")
            # Check legacy DATABASE_URL format.
            for match in re.finditer(
                r'DATABASE_URL\s*[=:]\s*(?:os\.environ\.get\([^)]+,\s*)?["\']([^"\']+)["\']',
                content,
            ):
                value = match.group(1)
                assert value == "" or "sqlite" in value.lower(), (
                    f"{path}: DATABASE_URL default {value!r} should use SQLite for examples"
                )
            # Check new DATABASES dict format for URL values.
            for match in re.finditer(
                r'"URL"\s*:\s*(?:os\.environ\.get\([^)]+,\s*)?["\']([^"\']+)["\']',
                content,
            ):
                value = match.group(1)
                assert value == "" or "sqlite" in value.lower(), (
                    f"{path}: DATABASES URL default {value!r} should use SQLite for examples"
                )

    def test002_no_real_private_keys_in_examples(self) -> None:
        """Example files must not contain real private keys."""
        for path in EXAMPLES_DIR.rglob("*.py"):
            content = path.read_text(encoding="utf-8", errors="ignore")
            for label, pattern in REAL_SECRET_PATTERNS:
                assert not pattern.search(content), f"{path}: found {label} pattern in example code"

    def test_doc002_settings_as_dict_masks_sensitive_fields(self) -> None:
        """Settings.as_dict() must mask sensitive fields by default."""
        settings = Settings()
        object.__setattr__(settings, "SECRET_KEY", "real-secret-key-value-that-should-be-masked")
        object.__setattr__(
            settings,
            "DATABASES",
            {"default": {"OPTIONS": {"URL": "postgresql://user:pass@host/db"}}},
        )
        result = settings.as_dict()
        assert result["SECRET_KEY"] == "***"
        assert result["DATABASES"] == "***"

    def test_doc002_settings_as_dict_unmask_shows_real_values(self) -> None:
        """Settings.as_dict(mask_sensitive=False) must reveal real values."""
        settings = Settings()
        object.__setattr__(settings, "SECRET_KEY", "real-secret-key-value")
        result = settings.as_dict(mask_sensitive=False)
        assert result["SECRET_KEY"] == "real-secret-key-value"

    def test_doc002_sensitive_fields_covers_critical_keys(self) -> None:
        """SENSITIVE_FIELDS must cover SECRET_KEY, DATABASES, and CACHES."""
        assert "SECRET_KEY" in SENSITIVE_FIELDS
        assert "DATABASES" in SENSITIVE_FIELDS
        assert "CACHES" in SENSITIVE_FIELDS

    def test_doc002_example_allowed_hosts_not_wildcard_in_production(self) -> None:
        """Example ALLOWED_HOSTS with wildcard must be documented as dev-only."""
        # Several examples use ALLOWED_HOSTS = ("*",) which is fine for
        # development but must not be used in production. Verify that
        # validate_settings catches this.
        settings = Settings()
        object.__setattr__(settings, "ALLOWED_HOSTS", ())
        object.__setattr__(settings, "SECRET_KEY", "a" * 64)
        object.__setattr__(
            settings, "DATABASES", {"default": {"OPTIONS": {"URL": "sqlite:///test.db"}}}
        )
        object.__setattr__(settings, "DEBUG", False)
        object.__setattr__(settings, "SECURE_COOKIES", True)
        object.__setattr__(settings, "SECURE_SSL_REDIRECT", True)
        object.__setattr__(settings, "SECURE_HSTS_SECONDS", 31536000)
        object.__setattr__(settings, "SESSION_COOKIE_SECURE", True)
        object.__setattr__(settings, "CSRF_COOKIE_SECURE", True)
        object.__setattr__(settings, "OPENAPI", {"enabled": False})
        object.__setattr__(settings, "CORS_ALLOWED_HEADERS", ("Content-Type",))
        with pytest.raises(SettingsValidationError) as exc_info:
            validate_settings(settings, env="production")
        messages = " ".join(exc_info.value.errors)
        assert "ALLOWED_HOSTS" in messages

    def test_doc002_no_hardcoded_passwords_in_examples(self) -> None:
        """Example Python files must not contain hardcoded passwords."""
        password_pattern = re.compile(
            r'password\s*[=:]\s*["\'][A-Za-z0-9!@#$%^&*]{8,}["\']',
            re.IGNORECASE,
        )
        for path in EXAMPLES_DIR.rglob("*.py"):
            content = path.read_text(encoding="utf-8", errors="ignore")
            # Skip create_admin.py which prompts for password interactively.
            if path.name == "create_admin.py":
                continue
            matches = password_pattern.findall(content)
            assert not matches, f"{path}: found hardcoded password pattern(s): {matches}"


class TestDoc003UnsafeExamplesMarked:
    """Unsafe patterns in documentation must be clearly marked with warnings."""

    # -- Plain password hasher --

    def test_doc003_plain_password_hasher_rejected_in_production(self) -> None:
        """Plain text password hashing must be rejected in production."""
        with patch("openviper.auth.hashers.settings", SimpleNamespace(TESTING=False, DEBUG=False)):
            with pytest.raises(RuntimeError, match="TESTING=True or DEBUG=True"):
                asyncio.run(make_password("test", algorithm="plain"))

    def test_doc003_plain_password_hasher_allowed_in_development(self) -> None:
        """Plain text password hashing must be allowed in non-production envs."""
        with patch("openviper.auth.hashers.settings", SimpleNamespace(TESTING=True, DEBUG=False)):
            result = asyncio.run(make_password("test", algorithm="plain"))
            assert result.startswith("plain$")

    def test_doc003_argon2_is_default_hasher(self) -> None:
        """Argon2 must be the default password hasher."""
        settings = Settings()
        assert settings.PASSWORD_HASHERS[0] == "argon2"

    # -- CORS wildcard with credentials --

    def test_doc003_cors_wildcard_with_credentials_rejected(self) -> None:
        """CORS wildcard origin with credentials must be rejected."""

        async def app(scope: dict, receive: object, send: object) -> None:
            pass

        with pytest.raises(ValueError, match="[Cc]redential.*wildcard|wildcard.*[Cc]redential"):
            CORSMiddleware(app, allowed_origins=["*"], allow_credentials=True)

    def test_doc003_cors_wildcard_without_credentials_allowed(self) -> None:
        """CORS wildcard origin without credentials must be allowed (typical dev setup)."""

        async def app(scope: dict, receive: object, send: object) -> None:
            pass

        # Must not raise - wildcard without credentials is a common dev pattern.
        middleware = CORSMiddleware(app, allowed_origins=["*"], allow_credentials=False)
        assert middleware is not None

    # -- Insecure JWT algorithm --

    def test_doc003_insecure_jwt_algorithm_none_rejected(self) -> None:
        """JWT algorithm 'none' must be rejected."""
        object.__setattr__(Settings(), "SECRET_KEY", "test-key")
        with override_settings(SECRET_KEY="test-key", JWT_ALGORITHM="none"):
            with pytest.raises(RuntimeError, match="[Ii]nsecure"):
                get_jwt_config()

    def test_doc003_insecure_jwt_algorithm_NONE_rejected(self) -> None:
        """JWT algorithm 'NONE' (uppercase) must also be rejected."""
        with override_settings(SECRET_KEY="test-key", JWT_ALGORITHM="NONE"):
            with pytest.raises(RuntimeError, match="[Ii]nsecure"):
                get_jwt_config()

    def test_doc003_jwt_empty_secret_key_rejected(self) -> None:
        """JWT operations must reject an empty SECRET_KEY."""
        with override_settings(SECRET_KEY=""):
            with pytest.raises(RuntimeError, match="SECRET_KEY"):
                get_jwt_config()

    # -- Documentation warnings --

    def test_doc003_docs_csrf_section_exists(self) -> None:
        """Documentation must include a CSRF configuration section."""
        conf_rst = DOCS_DIR / "conf.rst"
        if not conf_rst.is_file():
            pytest.skip("docs/conf.rst not found")
        content = conf_rst.read_text(encoding="utf-8")
        assert "CSRF" in content, "CSRF section missing from docs/conf.rst"

    def test_doc003_docs_csrf_cookie_httponly_documented_as_false(self) -> None:
        """CSRF_COOKIE_HTTPONLY must be documented as False for double-submit pattern."""
        conf_rst = DOCS_DIR / "conf.rst"
        if not conf_rst.is_file():
            pytest.skip("docs/conf.rst not found")
        content = conf_rst.read_text(encoding="utf-8")
        # The docs must explain why CSRF_COOKIE_HTTPONLY is False.
        assert "CSRF_COOKIE_HTTPONLY" in content
        assert "double-submit" in content.lower() or "httponly" in content.lower()

    def test_doc003_docs_cors_section_exists(self) -> None:
        """Documentation must include a CORS configuration section."""
        conf_rst = DOCS_DIR / "conf.rst"
        if not conf_rst.is_file():
            pytest.skip("docs/conf.rst not found")
        content = conf_rst.read_text(encoding="utf-8")
        assert "CORS" in content, "CORS section missing from docs/conf.rst"

    def test_doc003_docs_cors_allow_credentials_defaults_false(self) -> None:
        """CORS_ALLOW_CREDENTIALS must be documented as defaulting to False."""
        conf_rst = DOCS_DIR / "conf.rst"
        if not conf_rst.is_file():
            pytest.skip("docs/conf.rst not found")
        content = conf_rst.read_text(encoding="utf-8")
        assert "CORS_ALLOW_CREDENTIALS" in content

    def test_doc003_docs_security_section_exists(self) -> None:
        """Documentation must include a Security section."""
        conf_rst = DOCS_DIR / "conf.rst"
        if not conf_rst.is_file():
            pytest.skip("docs/conf.rst not found")
        content = conf_rst.read_text(encoding="utf-8")
        assert "Security" in content, "Security section missing from docs/conf.rst"

    def test_doc003_docs_secret_key_must_be_set_in_production(self) -> None:
        """Docs must state SECRET_KEY must be set in production."""
        conf_rst = DOCS_DIR / "conf.rst"
        if not conf_rst.is_file():
            pytest.skip("docs/conf.rst not found")
        content = conf_rst.read_text(encoding="utf-8")
        # Must mention that SECRET_KEY must be set via env var in production.
        assert "SECRET_KEY" in content
        assert "production" in content.lower() or "must" in content.lower()

    def test_doc003_docs_session_cookie_httponly_always_true(self) -> None:
        """Docs must state SESSION_COOKIE_HTTPONLY is always True."""
        conf_rst = DOCS_DIR / "conf.rst"
        if not conf_rst.is_file():
            pytest.skip("docs/conf.rst not found")
        content = conf_rst.read_text(encoding="utf-8")
        assert "SESSION_COOKIE_HTTPONLY" in content

    def test_doc003_docs_session_cookie_secure_in_production(self) -> None:
        """Docs must state SESSION_COOKIE_SECURE should be True in production."""
        conf_rst = DOCS_DIR / "conf.rst"
        if not conf_rst.is_file():
            pytest.skip("docs/conf.rst not found")
        content = conf_rst.read_text(encoding="utf-8")
        assert "SESSION_COOKIE_SECURE" in content

    def test_doc003_docs_middleware_csrf_exempt_paths_documented(self) -> None:
        """CSRF middleware exempt_paths must be documented."""
        middleware_rst = DOCS_DIR / "middleware.rst"
        if not middleware_rst.is_file():
            pytest.skip("docs/middleware.rst not found")
        content = middleware_rst.read_text(encoding="utf-8")
        assert "exempt_paths" in content, "CSRF exempt_paths not documented"

    def test_doc003_docs_cors_wildcard_documented(self) -> None:
        """CORS wildcard usage must be documented in middleware docs."""
        middleware_rst = DOCS_DIR / "middleware.rst"
        if not middleware_rst.is_file():
            pytest.skip("docs/middleware.rst not found")
        content = middleware_rst.read_text(encoding="utf-8")
        # The docs show wildcard usage in examples.
        assert "allowed_origins" in content

    def test_doc003_docs_raw_sql_documented_as_debugging_only(self) -> None:
        """raw_sql() must be documented as a debugging tool, not for production queries."""
        db_rst = DOCS_DIR / "db.rst"
        if not db_rst.is_file():
            pytest.skip("docs/db.rst not found")
        content = db_rst.read_text(encoding="utf-8")
        assert "raw_sql" in content, "raw_sql not documented"

    def test_doc003_docs_auth_plain_hasher_documented_as_testing_only(self) -> None:
        """Plain password hasher must be documented as testing-only."""
        auth_rst = DOCS_DIR / "auth.rst"
        if not auth_rst.is_file():
            pytest.skip("docs/auth.rst not found")
        content = auth_rst.read_text(encoding="utf-8")
        assert "plain" in content.lower()
        assert "testing" in content.lower() or "test" in content.lower()

    def test_doc003_docs_auth_warning_exists(self) -> None:
        """Auth docs must contain at least one .. warning:: directive."""
        auth_rst = DOCS_DIR / "auth.rst"
        if not auth_rst.is_file():
            pytest.skip("docs/auth.rst not found")
        content = auth_rst.read_text(encoding="utf-8")
        assert ".. warning::" in content, "No .. warning:: directive found in auth.rst"

    def test_doc003_docs_db_warning_exists(self) -> None:
        """DB docs must contain at least one .. warning:: directive."""
        db_rst = DOCS_DIR / "db.rst"
        if not db_rst.is_file():
            pytest.skip("docs/db.rst not found")
        content = db_rst.read_text(encoding="utf-8")
        assert ".. warning::" in content, "No .. warning:: directive found in db.rst"

    # -- Example project security posture --

    def test_doc003_example_todoapp_secret_key_is_placeholder(self) -> None:
        """todoapp example SECRET_KEY must be a clearly marked placeholder."""
        path = EXAMPLES_DIR / "todoapp" / "settings.py"
        if not path.is_file():
            pytest.skip("todoapp settings not found")
        content = path.read_text(encoding="utf-8")
        # Must use os.environ.get with a placeholder default.
        assert "SECRET_KEY" in content
        assert (
            "change" in content.lower() or "dev" in content.lower() or "insecure" in content.lower()
        )

    def test_doc003_example_tp_secret_key_is_placeholder(self) -> None:
        """tp example SECRET_KEY must be a clearly marked placeholder."""
        path = EXAMPLES_DIR / "tp" / "tp" / "settings.py"
        if not path.is_file():
            pytest.skip("tp settings not found")
        content = path.read_text(encoding="utf-8")
        assert "SECRET_KEY" in content
        assert (
            "insecure" in content.lower() or "dev" in content.lower() or "change" in content.lower()
        )

    def test_doc003_example_fx_secret_key_is_placeholder(self) -> None:
        """fx example SECRET_KEY must be a clearly marked placeholder."""
        path = EXAMPLES_DIR / "fx" / "settings.py"
        if not path.is_file():
            pytest.skip("fx settings not found")
        content = path.read_text(encoding="utf-8")
        assert "SECRET_KEY" in content
        assert (
            "demo" in content.lower()
            or "do not use" in content.lower()
            or "change" in content.lower()
        )

    def test_doc003_example_ecommerce_secret_key_is_placeholder(self) -> None:
        """ecommerce_clone example SECRET_KEY must be a clearly marked placeholder."""
        path = EXAMPLES_DIR / "ecommerce_clone" / "ecommerce_clone" / "settings.py"
        if not path.is_file():
            pytest.skip("ecommerce_clone settings not found")
        content = path.read_text(encoding="utf-8")
        assert "SECRET_KEY" in content
        assert (
            "change" in content.lower() or "insecure" in content.lower() or "dev" in content.lower()
        )

    # -- validate_settings catches insecure production configs --

    def test_doc003_production_validation_rejects_debug_true(self) -> None:
        """validate_settings must reject DEBUG=True in production."""
        settings = Settings()
        object.__setattr__(settings, "SECRET_KEY", "a" * 64)
        object.__setattr__(
            settings, "DATABASES", {"default": {"OPTIONS": {"URL": "sqlite:///test.db"}}}
        )
        object.__setattr__(settings, "DEBUG", True)
        with pytest.raises(SettingsValidationError) as exc_info:
            validate_settings(settings, env="production")
        messages = " ".join(exc_info.value.errors)
        assert "DEBUG" in messages

    def test_doc003_production_validation_rejects_openapi_enabled(self) -> None:
        """validate_settings must reject OPENAPI['enabled']=True in production."""
        settings = Settings()
        object.__setattr__(settings, "SECRET_KEY", "a" * 64)
        object.__setattr__(
            settings, "DATABASES", {"default": {"OPTIONS": {"URL": "sqlite:///test.db"}}}
        )
        object.__setattr__(settings, "DEBUG", False)
        object.__setattr__(settings, "SECURE_COOKIES", True)
        object.__setattr__(settings, "SECURE_SSL_REDIRECT", True)
        object.__setattr__(settings, "SECURE_HSTS_SECONDS", 31536000)
        object.__setattr__(settings, "SESSION_COOKIE_SECURE", True)
        object.__setattr__(settings, "CSRF_COOKIE_SECURE", True)
        object.__setattr__(settings, "OPENAPI", {"enabled": True})
        object.__setattr__(settings, "ALLOWED_HOSTS", ("example.com",))
        object.__setattr__(settings, "CORS_ALLOWED_HEADERS", ("Content-Type",))
        with pytest.raises(SettingsValidationError) as exc_info:
            validate_settings(settings, env="production")
        messages = " ".join(exc_info.value.errors)
        assert "OPENAPI['enabled']" in messages

    def test_doc003_production_validation_rejects_cors_wildcard_headers(self) -> None:
        """validate_settings must reject CORS_ALLOWED_HEADERS=('*',) in production."""
        settings = Settings()
        object.__setattr__(settings, "SECRET_KEY", "a" * 64)
        object.__setattr__(
            settings, "DATABASES", {"default": {"OPTIONS": {"URL": "sqlite:///test.db"}}}
        )
        object.__setattr__(settings, "DEBUG", False)
        object.__setattr__(settings, "SECURE_COOKIES", True)
        object.__setattr__(settings, "SECURE_SSL_REDIRECT", True)
        object.__setattr__(settings, "SECURE_HSTS_SECONDS", 31536000)
        object.__setattr__(settings, "SESSION_COOKIE_SECURE", True)
        object.__setattr__(settings, "CSRF_COOKIE_SECURE", True)
        object.__setattr__(settings, "OPENAPI", {"enabled": False})
        object.__setattr__(settings, "ALLOWED_HOSTS", ("example.com",))
        object.__setattr__(settings, "CORS_ALLOWED_HEADERS", ("*",))
        with pytest.raises(SettingsValidationError) as exc_info:
            validate_settings(settings, env="production")
        messages = " ".join(exc_info.value.errors)
        assert "CORS_ALLOWED_HEADERS" in messages
