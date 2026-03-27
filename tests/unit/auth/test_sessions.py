"""Unit tests for openviper.auth.sessions module (Compatibility layer)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.session.utils import _is_valid_session_key
from openviper.auth.sessions import (
    clear_session_cache,
    create_session,
    delete_session,
    generate_session_key,
    get_user_from_session,
)


class TestGenerateSessionKey:
    """Tests for generate_session_key function."""

    def test_generates_url_safe_key(self) -> None:
        key = generate_session_key()
        assert all(c.isalnum() or c in ("-", "_") for c in key)

    def test_generates_unique_keys(self) -> None:
        keys = {generate_session_key() for _ in range(100)}
        assert len(keys) == 100

    def test_generates_key_with_sufficient_entropy(self) -> None:
        key = generate_session_key()
        assert len(key) >= 60


class TestIsValidSessionKey:
    """Tests for _is_valid_session_key function."""

    def test_valid_key_returns_true(self) -> None:
        assert _is_valid_session_key("abc123XYZ_-abcdefghijk1234567890") is True

    def test_empty_string_returns_false(self) -> None:
        assert _is_valid_session_key("") is False

    def test_none_returns_false(self) -> None:
        assert _is_valid_session_key(None) is False


class TestCreateSession:
    """Tests for create_session function."""

    @pytest.mark.asyncio
    async def test_creates_session_delegates_to_store(self) -> None:
        from openviper.auth.session.store import Session

        mock_store = MagicMock()
        mock_session = Session(key="test_key", data={})
        mock_store.create = AsyncMock(return_value=mock_session)

        with patch("openviper.auth.sessions.get_session_store", return_value=mock_store):
            key = await create_session(user_id=42)
            assert key == "test_key"
            mock_store.create.assert_called_once_with(42, None)


class TestGetUserFromSession:
    """Tests for get_user_from_session function."""

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_cookie(self) -> None:
        result = await get_user_from_session("other_cookie=value")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_user_from_store(self) -> None:
        mock_user = MagicMock()
        mock_store = MagicMock()
        mock_store.get_user = AsyncMock(return_value=mock_user)

        with patch("openviper.auth.sessions.get_session_store", return_value=mock_store):
            result = await get_user_from_session("sessionid=valid_key_1234567890abcdefghij123")
            assert result is mock_user


class TestDeleteSession:
    """Tests for delete_session function."""

    @pytest.mark.asyncio
    async def test_deletes_session_delegates_to_store(self) -> None:
        mock_store = MagicMock()
        mock_store.delete = AsyncMock()

        with patch("openviper.auth.sessions.get_session_store", return_value=mock_store):
            await delete_session("test-session-key")
            mock_store.delete.assert_called_once_with("test-session-key")


class TestClearSessionCache:
    """Tests for clear_session_cache function."""

    @pytest.mark.asyncio
    async def test_clears_cache(self) -> None:
        mock_cache = MagicMock()
        mock_cache.keys = AsyncMock(
            side_effect=[
                ["session:abc", "session:def"],
                ["session_user:abc"],
            ]
        )
        mock_cache.delete = AsyncMock()

        with patch("openviper.auth.sessions.get_cache", return_value=mock_cache):
            await clear_session_cache()

        assert mock_cache.delete.call_count == 3
        deleted = {call.args[0] for call in mock_cache.delete.call_args_list}
        assert deleted == {"session:abc", "session:def", "session_user:abc"}
