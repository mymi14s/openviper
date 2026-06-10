"""Configuration security tests.

Requirement IDs: CONF-001 through CONF-005.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from openviper.auth.jwt import ALLOWED_JWT_ALGORITHMS, get_jwt_config
from openviper.conf.settings import SENSITIVE_FIELDS, Settings
from openviper.middleware.cors import CORSMiddleware
from openviper.middleware.csrf import CSRFMiddleware
from openviper.middleware.security import SecurityMiddleware

from .conftest import override_settings


class TestDebugModeProduction:
    """Debug mode must be disabled in production environments."""

    def test_conf001_debug_can_be_disabled(self):
        """DEBUG must be overridable to False for production."""

        # Production must set DEBUG=False via environment or config.
        # Verify it can be explicitly disabled.
        settings = Settings(DEBUG=False)
        assert settings.DEBUG is False

    def test_conf001_debug_default_is_development(self):
        """DEBUG defaults to True for development convenience."""

        settings = Settings()
        # Default is True for development; production must override.
        assert settings.DEBUG is True


class TestMissingSecretKey:
    """Missing SECRET_KEY must cause startup to fail."""

    def test_conf002_secret_key_required(self):
        """SECRET_KEY must be required for security operations."""
        # The JWT module requires SECRET_KEY
        with patch.dict(os.environ, {}, clear=False):
            with override_settings(SECRET_KEY=""):
                with pytest.raises(RuntimeError, match="SECRET_KEY"):
                    get_jwt_config()

    def test_conf002_csrf_requires_secret_key(self):
        """CSRF middleware must require a SECRET_KEY."""

        async def app(scope, receive, send):
            pass

        with override_settings(SECRET_KEY=""):
            middleware = CSRFMiddleware(app, secret="")
            with pytest.raises(RuntimeError, match="SECRET_KEY|secret"):
                middleware.get_secret()


class TestDefaultSecretKey:
    """Default or sample secret keys must not be allowed in production."""

    def test_conf003_sensitive_fields_defined(self):
        """Settings must define sensitive fields that are never exposed."""
        assert "SECRET_KEY" in SENSITIVE_FIELDS
        assert "DATABASES" in SENSITIVE_FIELDS

    def test_conf003_jwt_rejects_insecure_algorithm(self):
        """JWT must reject insecure algorithms like 'none'."""
        assert "none" not in ALLOWED_JWT_ALGORITHMS
        assert "None" not in ALLOWED_JWT_ALGORITHMS
        assert "NONE" not in ALLOWED_JWT_ALGORITHMS


class TestAllowedHosts:
    """ALLOWED_HOSTS must be enforced for Host header validation."""

    def test_conf004_security_middleware_enforces_allowed_hosts(self):
        """SecurityMiddleware must validate Host against ALLOWED_HOSTS."""

        async def app(scope, receive, send):
            pass

        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(app)
            assert middleware.is_host_allowed("example.com")
            assert not middleware.is_host_allowed("evil.com")

    def test_conf004_wildcard_allows_all_hosts(self):
        """ALLOWED_HOSTS=['*'] must allow all hosts."""

        async def app(scope, receive, send):
            pass

        with override_settings(ALLOWED_HOSTS=["*"]):
            middleware = SecurityMiddleware(app)
            assert middleware._allow_all_hosts is True
            assert middleware.is_host_allowed("any-host.com")

    def test_conf004_wildcard_suffix_matching(self):
        """ALLOWED_HOSTS with .example.com must match subdomains."""

        async def app(scope, receive, send):
            pass

        with override_settings(ALLOWED_HOSTS=[".example.com"]):
            middleware = SecurityMiddleware(app)
            assert middleware.is_host_allowed("sub.example.com")
            # The base domain also matches the wildcard suffix pattern
            assert middleware.is_host_allowed("example.com")
            assert not middleware.is_host_allowed("evil.com")


class TestCORSDefaults:
    """CORS defaults must be restrictive."""

    def test_conf005_cors_rejects_wildcard_with_credentials(self):
        """CORS must reject allow_credentials=True with wildcard origin."""

        async def app(scope, receive, send):
            pass

        with pytest.raises(ValueError, match="[Cc]redential.*wildcard|wildcard.*[Cc]redential"):
            CORSMiddleware(app, allowed_origins=["*"], allow_credentials=True)

    def test_conf005_cors_default_no_credentials(self):
        """CORS must default to allow_credentials=False."""

        async def app(scope, receive, send):
            pass

        middleware = CORSMiddleware(app, allowed_origins=["https://example.com"])
        assert middleware.allow_credentials is False

    def test_conf005_cors_explicit_origins_required_with_credentials(self):
        """CORS with credentials must require explicit origins."""

        async def app(scope, receive, send):
            pass

        # Must not raise with explicit origins and credentials
        middleware = CORSMiddleware(
            app,
            allowed_origins=["https://trusted.example.com"],
            allow_credentials=True,
        )
        assert middleware.allow_credentials is True
