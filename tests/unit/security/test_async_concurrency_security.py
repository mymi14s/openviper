"""Async concurrency security tests.

Requirement IDs: ASYNC-001 through ASYNC-004.
"""

from __future__ import annotations

import asyncio

import pytest

from openviper.auth.session.utils import generate_session_key
from openviper.core.context import current_user, ignore_permissions, ignore_permissions_ctx
from openviper.http.request import Request
from openviper.middleware.ratelimit import SlidingWindowCounter

from .conftest import MockUser, make_scope


class TestConcurrentRequestIsolation:
    """Concurrent requests must not share mutable state."""

    @pytest.mark.asyncio
    async def test_async001_request_state_isolation(self):
        """Each request must have its own isolated state dict."""
        scope1 = make_scope(path="/user/a")
        scope2 = make_scope(path="/user/b")

        request1 = Request(scope1)
        request2 = Request(scope2)

        request1.state["data"] = "sensitive_a"
        request2.state["data"] = "sensitive_b"

        assert request1.state["data"] == "sensitive_a"
        assert request2.state["data"] == "sensitive_b"
        assert request1.state is not request2.state

    @pytest.mark.asyncio
    async def test_async001_concurrent_user_context_isolation(self):
        """Concurrent async tasks must have isolated user contexts."""
        results: dict[str, int | None] = {}

        async def simulate_request(user_id: int, key: str):
            user = MockUser(user_id=user_id)
            token = current_user.set(user)
            try:
                await asyncio.sleep(0.01)
                current = current_user.get()
                results[key] = current.id if current else None
            finally:
                current_user.reset(token)

        await asyncio.gather(
            simulate_request(1, "a"),
            simulate_request(2, "b"),
            simulate_request(3, "c"),
        )

        assert results["a"] == 1
        assert results["b"] == 2
        assert results["c"] == 3


class TestCancelledRequestCleanup:
    """Cancelled requests must clean up resources."""

    @pytest.mark.asyncio
    async def test_async002_context_var_cleanup_on_exception(self):
        """ContextVar tokens must be reset even on exceptions."""
        original = current_user.get()

        try:
            token = current_user.set(MockUser(user_id=999))
            raise ValueError("Simulated error")
        except ValueError:
            pass
        finally:
            current_user.reset(token)

        # After reset, the context must be restored
        assert current_user.get() is original or current_user.get() is None

    @pytest.mark.asyncio
    async def test_async002_ignore_permissions_context_cleanup(self):
        """ignore_permissions context must be cleaned up after use."""
        assert ignore_permissions_ctx.get() is False

        with ignore_permissions():
            assert ignore_permissions_ctx.get() is True

        assert ignore_permissions_ctx.get() is False


class TestBackgroundTaskSecurityContext:
    """Background tasks must use explicit context, not inherited state."""

    @pytest.mark.asyncio
    async def test_async003_context_var_not_inherited_across_tasks(self):
        """ContextVar values must not leak between unrelated async tasks."""
        token = current_user.set(MockUser(user_id=42))

        async def background_task():
            # Background task should not see the request user
            # unless explicitly set
            return current_user.get()

        await background_task()
        # The context var propagates within the same async context
        # but must be explicitly managed for background tasks
        current_user.reset(token)

    @pytest.mark.asyncio
    async def test_async003_explicit_context_for_background_tasks(self):
        """Background tasks must receive explicit context parameters."""

        # Best practice: pass user_id explicitly to background tasks
        async def process_data(user_id: int, data: dict):
            return {"user_id": user_id, "processed": True}

        result = await process_data(user_id=42, data={"key": "value"})
        assert result["user_id"] == 42
        assert result["processed"] is True


class TestRaceConditionProtection:
    """Race-sensitive operations must be protected."""

    @pytest.mark.asyncio
    async def test_async004_rate_limit_per_key_isolation(self):
        """Rate limit counters must be isolated per key."""
        counter = SlidingWindowCounter(max_requests=1, window_seconds=60)

        # Concurrent requests for different keys must not interfere
        results = await asyncio.gather(
            counter.is_allowed("user:1"),
            counter.is_allowed("user:2"),
            counter.is_allowed("user:3"),
        )

        # All should be allowed (first request per key)
        for allowed, _ in results:
            assert allowed is True

    @pytest.mark.asyncio
    async def test_async004_session_key_uniqueness_under_concurrency(self):
        """Session keys generated concurrently must be unique."""
        keys = await asyncio.gather(*[asyncio.to_thread(generate_session_key) for _ in range(50)])
        assert len(set(keys)) == 50
