import pytest

from openviper.exceptions import MethodNotAllowed
from openviper.http.request import Request
from openviper.http.response import Response
from openviper.http.views import View


class DummyView(View):
    async def get(self, request):
        return Response("get")

    async def post(self, request):
        return Response("post")


@pytest.fixture
def mock_request():
    scope = {"type": "http", "method": "get", "path": "/"}
    return Request(scope)


@pytest.mark.asyncio
async def test_view_dispatch(mock_request):
    view = DummyView()

    # GET works
    mock_request._scope["method"] = "get"
    resp = await view.dispatch(mock_request)
    assert resp.body == b"get"

    # POST works
    mock_request._scope["method"] = "post"
    resp = await view.dispatch(mock_request)
    assert resp.body == b"post"

    # PUT fails
    mock_request._scope["method"] = "put"
    with pytest.raises(MethodNotAllowed) as exc:
        await view.dispatch(mock_request)
    assert "GET, POST" in str(exc.value.headers.get("Allow"))


@pytest.mark.asyncio
async def test_view_options(mock_request):
    view = DummyView()
    mock_request._scope["method"] = "options"
    resp = await view.dispatch(mock_request)
    assert resp.status_code == 204
    assert resp.headers["allow"] == "GET, OPTIONS, POST"


def test_view_allowed_methods():
    view = DummyView()
    allowed = view._allowed_methods()
    assert allowed == ["GET", "OPTIONS", "POST"]


@pytest.mark.asyncio
async def test_view_as_view(mock_request):
    ViewFunc = DummyView.as_view(custom_var=123)

    mock_request._scope["method"] = "get"
    resp = await ViewFunc(mock_request)
    assert resp.body == b"get"

    # Check attributes stored on the callable
    assert ViewFunc.__name__ == "DummyView"
    assert ViewFunc.view_initkwargs == {"custom_var": 123}


def test_view_as_view_invalid_kwargs():
    with pytest.raises(TypeError, match="invalid keyword 'get'"):
        DummyView.as_view(get=True)


def test_view_register():
    class MockRouter:
        def __init__(self):
            self.calls = []

        def route(self, path, methods, name):
            def decorator(handler):
                self.calls.append(
                    {"path": path, "methods": methods, "name": name, "handler": handler}
                )
                return handler

            return decorator

    r = MockRouter()
    DummyView.register(r, "/dummy", name="dummy-route", custom_var=456)

    assert len(r.calls) == 1
    call = r.calls[0]
    assert call["path"] == "/dummy"
    assert call["methods"] == ["GET", "POST", "OPTIONS"]
    assert call["name"] == "dummy-route"

    # Verify the decorator callback is called
    handler = call["handler"]
    assert getattr(handler, "view_class", None) is DummyView
    assert handler.view_initkwargs == {"custom_var": 456}


def test_view_register_no_name():
    class MockRouter:
        def route(self, path, methods, name):
            def decorator(handler):
                self.name = name
                return handler

            return decorator

    r = MockRouter()
    DummyView.register(r, "/dummy_no_name")
    assert r.name == "DummyView"
