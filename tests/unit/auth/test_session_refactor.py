"""Unit tests for the refactored session system."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.session.middleware import SessionMiddleware
from openviper.auth.session.store import (
    DatabaseSessionStore,
    Session,
    _reset_store_instance,
    get_session_store,
)
from openviper.http.request import Request


@pytest.fixture
def mock_store():
    store = MagicMock(spec=DatabaseSessionStore)
    store.create = AsyncMock()
    store.load = AsyncMock()
    store.save = AsyncMock()
    store.delete = AsyncMock()
    store.get_user = AsyncMock()
    return store


@pytest.fixture
def mock_cache():
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    cache.delete = AsyncMock()
    cache.clear = AsyncMock()
    return cache


class TestSession:
    def test_session_data_access(self) -> None:
        session = Session(key="test", data={"foo": "bar"})
        assert session["foo"] == "bar"
        assert session.get("foo") == "bar"
        assert session.get("missing", "default") == "default"

    def test_session_modification_tracking(self) -> None:
        session = Session(key="test", data={"foo": "bar"})
        assert session._is_modified is False
        session["foo"] = "baz"
        assert session._is_modified is True

    @pytest.mark.asyncio
    async def test_session_save(self, mock_store) -> None:
        session = Session(key="test", data={"foo": "bar"}, store=mock_store)
        session["foo"] = "baz"
        await session.save()
        mock_store.save.assert_called_once_with("test", {"foo": "baz"})


class TestDatabaseSessionStore:
    @pytest.mark.asyncio
    async def test_create_returns_session_object(self, mock_cache) -> None:
        with patch("openviper.auth.session.store._ensure_table", new=AsyncMock()):
            with patch("openviper.auth.session.store.get_engine") as mock_engine:
                with patch("openviper.auth.session.store.get_cache", return_value=mock_cache):
                    mock_conn = MagicMock()
                    mock_conn.execute = AsyncMock()
                    mock_context = MagicMock()
                    mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
                    mock_context.__aexit__ = AsyncMock(return_value=None)
                    mock_engine.return_value = MagicMock(begin=MagicMock(return_value=mock_context))

                    store = DatabaseSessionStore()
                    session = await store.create(user_id=1, data={"a": 1})

                    assert isinstance(session, Session)
                    assert session.key is not None
                    assert session["a"] == 1
                    mock_cache.set.assert_called()


class TestRequestIntegration:
    def test_request_session_lazy_loading(self) -> None:
        scope = {"type": "http", "method": "GET", "path": "/"}
        request = Request(scope)
        session = request.session
        assert isinstance(session, Session)
        assert session.key == ""


class TestSessionMiddleware:
    @pytest.mark.asyncio
    async def test_middleware_loads_existing_session(self, mock_store) -> None:
        app = AsyncMock()
        middleware = SessionMiddleware(app, store=mock_store)

        scope = {
            "type": "http",
            "headers": [(b"cookie", b"sessionid=existing_key")],
        }
        receive = AsyncMock()
        send = AsyncMock()

        mock_session = Session(key="existing_key", data={"user_id": "1"}, store=mock_store)
        mock_store.load.return_value = mock_session

        await middleware(scope, receive, send)

        app.assert_called_once()
        assert scope["session"] == mock_session


class TestGetSessionStore:
    def setup_method(self) -> None:
        _reset_store_instance()

    def teardown_method(self) -> None:
        _reset_store_instance()

    def test_returns_database_store_by_default(self) -> None:
        store = get_session_store()
        assert isinstance(store, DatabaseSessionStore)

    def test_returns_singleton(self) -> None:
        store1 = get_session_store()
        store2 = get_session_store()
        assert store1 is store2

    def test_custom_dotted_path(self) -> None:
        with patch("openviper.auth.session.store.settings") as mock_settings:
            mock_settings.SESSION_STORE = "openviper.auth.session.store.DatabaseSessionStore"
            store = get_session_store()
            assert isinstance(store, DatabaseSessionStore)
