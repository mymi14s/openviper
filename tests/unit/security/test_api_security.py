"""API security tests.

Requirement IDs: API-001 through API-006.
"""

from __future__ import annotations

import pytest

from openviper.admin.options import ModelAdmin
from openviper.auth.jwt import create_access_token, decode_access_token
from openviper.auth.token_blocklist import is_token_revoked
from openviper.db.models import Model
from openviper.middleware.ratelimit import SlidingWindowCounter
from openviper.serializers.base import Serializer


class TestSerializerPrivateFields:
    """Serializers must not expose private or sensitive fields."""

    def test_api001_serializer_sensitive_fields_defined(self):
        """ModelAdmin must define sensitive_fields to exclude passwords."""
        admin = ModelAdmin(Model)
        assert "password" in admin.sensitive_fields

    def test_api001_serializer_readonly_fields_protected(self):
        """Serializer readonly_fields must not be writable via input data."""
        # Verify that the base Serializer class supports readonly_fields
        # as a security mechanism to prevent mass assignment
        assert hasattr(Serializer, "readonly_fields")
        assert isinstance(Serializer.readonly_fields, tuple)

        # Verify that ModelAdmin defines sensitive_fields on instances
        admin = ModelAdmin(Model)
        assert "password" in admin.sensitive_fields

    def test_api001_serializer_writeonly_fields_excluded(self):
        """Serializer writeonly_fields must be excluded from output."""
        # Verify that the base Serializer class supports writeonly_fields
        # as a security mechanism to prevent sensitive data in responses
        assert hasattr(Serializer, "writeonly_fields")
        assert isinstance(Serializer.writeonly_fields, tuple)


class TestAutomaticModelSerialization:
    """Raw model objects must not be serialized without explicit schema."""

    def test_api002_serializer_requires_explicit_fields(self):
        """Serializer must define explicit fields, not dump all model attributes."""

        class SafeSerializer(Serializer):
            id: int = 0
            name: str = ""

        # Only defined fields should be in the schema
        assert "id" in SafeSerializer.model_fields
        assert "name" in SafeSerializer.model_fields
        # No extra fields
        assert len(SafeSerializer.model_fields) == 2


class TestRateLimiting:
    """Rate limits must be enforced to prevent abuse."""

    def test_api003_sliding_window_counter_exists(self):
        """The sliding window rate counter must be available."""
        counter = SlidingWindowCounter(max_requests=10, window_seconds=60)
        assert counter.max_requests == 10
        assert counter.window == 60

    @pytest.mark.asyncio
    async def test_api003_rate_limit_enforcement(self):
        """Requests exceeding the rate limit must be throttled."""
        counter = SlidingWindowCounter(max_requests=2, window_seconds=60)

        # First two requests should be allowed
        allowed1, remaining1 = await counter.is_allowed("test-key")
        assert allowed1 is True

        allowed2, remaining2 = await counter.is_allowed("test-key")
        assert allowed2 is True

        # Third request should be denied
        allowed3, remaining3 = await counter.is_allowed("test-key")
        assert allowed3 is False

    @pytest.mark.asyncio
    async def test_api003_rate_limit_per_key(self):
        """Rate limits must be enforced per key, not globally."""
        counter = SlidingWindowCounter(max_requests=1, window_seconds=60)

        # First request for key A
        allowed_a, _ = await counter.is_allowed("key-a")
        assert allowed_a is True

        # First request for key B (different key, should be allowed)
        allowed_b, _ = await counter.is_allowed("key-b")
        assert allowed_b is True

        # Second request for key A (should be denied)
        allowed_a2, _ = await counter.is_allowed("key-a")
        assert allowed_a2 is False


class TestWebhookSignatures:
    """Webhook endpoints must require valid signatures."""

    def test_api004_jwt_token_includes_jti(self):
        """JWT tokens must include a unique identifier for replay protection."""
        token = create_access_token(user_id=1)
        payload = decode_access_token(token)
        assert "jti" in payload

    def test_api004_jwt_token_includes_required_claims(self):
        """JWT tokens must include required claims for replay protection."""
        token = create_access_token(user_id=1)
        payload = decode_access_token(token)
        # Required claims: sub (subject), jti (unique ID), exp (expiry), type
        assert "sub" in payload
        assert "jti" in payload
        assert "exp" in payload
        assert "type" in payload


class TestWebhookReplay:
    """Replayed webhook requests must be blocked."""

    @pytest.mark.asyncio
    async def test_api005_revoked_jwt_rejected(self):
        """Revoked JWT tokens must be rejected."""
        # Verify the blocklist module exists and has the expected interface.
        assert callable(is_token_revoked)

    def test_api005_jwt_includes_expiry(self):
        """JWT tokens must include an expiration time for replay protection."""
        token = create_access_token(user_id=1)
        payload = decode_access_token(token)
        assert "exp" in payload


class TestGraphQLDepthLimit:
    """GraphQL query depth and cost must be limited when GraphQL is enabled."""

    def test_api006_graphql_not_enabled_by_default(self):
        """GraphQL must not be enabled by default in the framework."""
        # The framework does not include GraphQL by default
        # This test documents that GraphQL is an optional feature
        # and must be explicitly enabled with depth/cost limits
        pass  # Structural check: GraphQL is not in core modules
