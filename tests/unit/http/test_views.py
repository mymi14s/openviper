"""Unit tests for openviper.http.views."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from openviper.exceptions import MethodNotAllowed
from openviper.http.response import JSONResponse, Response
from openviper.http.views import View

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_request(method: str = "GET") -> MagicMock:
    req = MagicMock()
    req.method = method.upper()
    return req


# ---------------------------------------------------------------------------
# Basic dispatch
# ---------------------------------------------------------------------------


class TestViewDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_get(self):
        class MyView(View):
            async def get(self, request, **kwargs):
                return Response(b"ok")

        view = MyView()
        resp = await view.dispatch(make_request("GET"))
        assert resp.body == b"ok"

    @pytest.mark.asyncio
    async def test_dispatch_post(self):
        class MyView(View):
            async def post(self, request, **kwargs):
                return Response(b"created", status_code=201)

        view = MyView()
        resp = await view.dispatch(make_request("POST"))
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_dispatch_unimplemented_raises_method_not_allowed(self):
        class OnlyGetView(View):
            async def get(self, request, **kwargs):
                return Response(b"ok")

        view = OnlyGetView()
        with pytest.raises(MethodNotAllowed):
            await view.dispatch(make_request("POST"))

    @pytest.mark.asyncio
    async def test_dispatch_method_not_in_http_method_names_raises(self):
        class MyView(View):
            pass

        view = MyView()
        req = make_request("CUSTOM")
        with pytest.raises(MethodNotAllowed):
            await view.dispatch(req)

    @pytest.mark.asyncio
    async def test_dispatch_kwargs_forwarded(self):
        class DetailView(View):
            async def get(self, request, pk=None, **kwargs):
                return JSONResponse({"pk": pk})

        view = DetailView()
        resp = await view.dispatch(make_request("GET"), pk=42)

        data = json.loads(resp.body)
        assert data["pk"] == 42


# ---------------------------------------------------------------------------
# Options method
# ---------------------------------------------------------------------------


class TestViewOptions:
    @pytest.mark.asyncio
    async def test_options_returns_204(self):
        class MyView(View):
            async def get(self, request, **kwargs):
                return Response(b"")

        view = MyView()
        resp = await view.dispatch(make_request("OPTIONS"))
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_options_allow_header_contains_get(self):
        class MyView(View):
            async def get(self, request, **kwargs):
                return Response(b"")

        view = MyView()
        resp = await view.dispatch(make_request("OPTIONS"))
        allow = resp.headers.get("allow")
        assert allow is not None
        assert "GET" in allow


# ---------------------------------------------------------------------------
# _allowed_methods
# ---------------------------------------------------------------------------


class TestAllowedMethods:
    def test_allowed_includes_implemented_methods(self):
        class MyView(View):
            async def get(self, req, **kw):
                return Response(b"")

            async def post(self, req, **kw):
                return Response(b"")

        view = MyView()
        allowed = view._allowed_methods()
        assert "GET" in allowed
        assert "POST" in allowed

    def test_allowed_excludes_unimplemented(self):
        class OnlyGetView(View):
            async def get(self, req, **kw):
                return Response(b"")

        view = OnlyGetView()
        allowed = view._allowed_methods()
        assert "POST" not in allowed
        assert "DELETE" not in allowed

    def test_allowed_methods_cached(self):
        class MyView(View):
            async def get(self, req, **kw):
                return Response(b"")

        view = MyView()
        a1 = view._allowed_methods()
        a2 = view._allowed_methods()
        assert a1 is a2


# ---------------------------------------------------------------------------
# as_view
# ---------------------------------------------------------------------------


class TestAsView:
    def test_as_view_returns_callable(self):
        class MyView(View):
            async def get(self, req, **kw):
                return Response(b"")

        handler = MyView.as_view()
        assert callable(handler)

    def test_as_view_preserves_metadata(self):
        class MyView(View):
            """My view docstring."""

            async def get(self, req, **kw):
                return Response(b"")

        handler = MyView.as_view()
        assert handler.__name__ == "MyView"
        assert handler.view_class is MyView

    def test_as_view_kwargs_stored_on_handler(self):
        class MyView(View):
            async def get(self, req, **kw):
                return Response(b"")

        handler = MyView.as_view(extra="value")
        assert handler.view_initkwargs == {"extra": "value"}

    def test_as_view_rejects_http_method_kwargs(self):
        class MyView(View):
            async def get(self, req, **kw):
                return Response(b"")

        with pytest.raises(TypeError, match="invalid keyword"):
            MyView.as_view(get="not_allowed")

    @pytest.mark.asyncio
    async def test_as_view_handler_creates_instance(self):
        class MyView(View):
            async def get(self, req, **kw):
                return Response(b"from_view")

        handler = MyView.as_view()
        resp = await handler(make_request("GET"))
        assert resp.body == b"from_view"


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


class TestRegister:
    def test_register_calls_router_route(self):
        class MyView(View):
            async def get(self, req, **kw):
                return Response(b"")

        router = MagicMock()
        router.route = MagicMock(return_value=lambda fn: fn)
        MyView.register(router, "/my-path")
        router.route.assert_called_once()
        call_kwargs = router.route.call_args
        assert "/my-path" in call_kwargs.args or call_kwargs.kwargs.get("path") == "/my-path"

    def test_register_includes_options_when_methods_exist(self):
        class MyView(View):
            async def get(self, req, **kw):
                return Response(b"")

        methods_used = []

        def fake_route(path, methods=None, name=None):
            if methods:
                methods_used.extend(methods)
            return lambda fn: fn

        router = MagicMock()
        router.route = fake_route
        MyView.register(router, "/path")
        assert "OPTIONS" in methods_used

    def test_register_with_custom_name(self):
        class MyView(View):
            async def get(self, req, **kw):
                return Response(b"")

        captured = {}

        def fake_route(path, methods=None, name=None):
            captured["name"] = name
            return lambda fn: fn

        router = MagicMock()
        router.route = fake_route
        MyView.register(router, "/path", name="custom-name")
        assert captured["name"] == "custom-name"


# ---------------------------------------------------------------------------
# View.__init__
# ---------------------------------------------------------------------------


class TestViewInit:
    def test_kwargs_set_as_attributes(self):
        view = View(my_attr="hello")
        assert view.my_attr == "hello"  # type: ignore[attr-defined]

    def test_allowed_methods_cache_is_class_level(self):
        # Cache is stored on the class, not the instance, so it survives
        # across the per-request instance creation done by as_view().
        _key = "_view_allowed_methods_cache"
        # Wipe any stale cache from a previous test run.
        if _key in View.__dict__:
            delattr(View, _key)  # type: ignore[attr-defined]
        view = View()
        assert _key not in type(view).__dict__
        view._allowed_methods()
        assert _key in type(view).__dict__
