"""Unit tests for openviper.auth.manager module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.backends.jwt_backend import JWTBackend
from openviper.auth.manager import AuthManager, _load_backend
from openviper.auth.models import AnonymousUser


class TestLoadBackend:
    """Tests for _load_backend function."""

    def test_loads_and_instantiates_backend(self):

        backend = _load_backend("openviper.auth.backends.jwt_backend.JWTBackend")


        assert isinstance(backend, JWTBackend)

    def test_raises_on_invalid_module(self):

        with pytest.raises(ModuleNotFoundError):
            _load_backend("nonexistent.module.Backend")

    def test_raises_on_invalid_class(self):

        with pytest.raises(AttributeError):
            _load_backend("openviper.auth.backends.jwt_backend.NonexistentClass")


class TestAuthManager:
    """Tests for AuthManager class."""

    @pytest.fixture
    def mock_backend_success(self):
        """Create a mock backend that successfully authenticates."""
        backend = MagicMock()
        user = MagicMock()
        user.is_active = True
        backend.authenticate = AsyncMock(return_value=(user, {"type": "test"}))
        return backend, user

    @pytest.fixture
    def mock_backend_fail(self):
        """Create a mock backend that fails to authenticate."""
        backend = MagicMock()
        backend.authenticate = AsyncMock(return_value=None)
        return backend

    def test_init_with_custom_backends(self, mock_backend_success):

        backend, _ = mock_backend_success
        manager = AuthManager(backends=[backend])

        assert len(manager._backends) == 1
        assert manager._backends[0] is backend

    def test_init_loads_default_backends(self):

        with patch("openviper.auth.manager.settings") as mock_settings:
            mock_settings.AUTH_BACKENDS = ("openviper.auth.backends.jwt_backend.JWTBackend",)
            manager = AuthManager()

        assert len(manager._backends) == 1

    def test_handles_backend_load_failure(self):

        with patch("openviper.auth.manager.settings") as mock_settings:
            mock_settings.AUTH_BACKENDS = (
                "nonexistent.backend.Backend",  # Invalid
                "openviper.auth.backends.jwt_backend.JWTBackend",  # Valid
            )
            manager = AuthManager()

        # Should have loaded only the valid backend
        assert len(manager._backends) == 1

    @pytest.mark.asyncio
    async def test_authenticate_returns_first_success(
        self, mock_backend_success, mock_backend_fail
    ):

        backend_success, expected_user = mock_backend_success

        manager = AuthManager(backends=[mock_backend_fail, backend_success])
        user, auth_info = await manager.authenticate({})

        assert user is expected_user
        assert auth_info["type"] == "test"

    @pytest.mark.asyncio
    async def test_authenticate_returns_anonymous_on_all_fail(self, mock_backend_fail):

        manager = AuthManager(backends=[mock_backend_fail])
        user, auth_info = await manager.authenticate({})

        assert isinstance(user, AnonymousUser)
        assert auth_info["type"] == "none"

    @pytest.mark.asyncio
    async def test_authenticate_skips_inactive_user(self):

        backend = MagicMock()
        inactive_user = MagicMock()
        inactive_user.is_active = False
        backend.authenticate = AsyncMock(return_value=(inactive_user, {"type": "test"}))

        manager = AuthManager(backends=[backend])
        user, auth_info = await manager.authenticate({})

        assert isinstance(user, AnonymousUser)

    @pytest.mark.asyncio
    async def test_authenticate_handles_backend_exception(self, mock_backend_success):

        failing_backend = MagicMock()
        failing_backend.authenticate = AsyncMock(side_effect=Exception("Backend error"))

        success_backend, expected_user = mock_backend_success

        manager = AuthManager(backends=[failing_backend, success_backend])
        user, auth_info = await manager.authenticate({})

        # Should continue to next backend and succeed
        assert user is expected_user

    @pytest.mark.asyncio
    async def test_authenticate_with_empty_backends(self):

        manager = AuthManager(backends=[])
        user, auth_info = await manager.authenticate({})

        assert isinstance(user, AnonymousUser)
        assert auth_info["type"] == "none"
