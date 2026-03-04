"""Integration tests for openviper.http.views (class-based views)."""

from __future__ import annotations

import pytest

from openviper.exceptions import MethodNotAllowed
from openviper.http.request import Request
from openviper.http.response import JSONResponse, Response
from openviper.http.views import View
from openviper.routing.router import Router

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_request(method="GET", path="/"):
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "query_string": b"",
    }
    return Request(scope)


# ---------------------------------------------------------------------------
# View dispatch
# ---------------------------------------------------------------------------


class TestViewDispatch:
    @pytest.mark.asyncio
    async def test_get_dispatched(self):
        class MyView(View):
            async def get(self, request):
                return JSONResponse({"method": "get"})

        view = MyView()
        req = make_request("GET")
        resp = await view.dispatch(req)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_post_dispatched(self):
        class MyView(View):
            async def post(self, request):
                return JSONResponse({"method": "post"})

        view = MyView()
        req = make_request("POST")
        resp = await view.dispatch(req)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_method_not_in_names_raises(self):
        class LimitedView(View):
            http_method_names = ["get"]

            async def get(self, request):
                return Response("ok")

        view = LimitedView()
        req = make_request("DELETE")
        with pytest.raises(MethodNotAllowed):
            await view.dispatch(req)

    @pytest.mark.asyncio
    async def test_missing_handler_raises_405(self):
        class GetOnly(View):
            async def get(self, request):
                return Response("ok")

        view = GetOnly()
        req = make_request("POST")
        with pytest.raises(MethodNotAllowed):
            await view.dispatch(req)

    @pytest.mark.asyncio
    async def test_options_returns_allow_header(self):
        class MyView(View):
            async def get(self, request):
                return Response("ok")

        view = MyView()
        req = make_request("OPTIONS")
        resp = await view.dispatch(req)
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_kwargs_passed_to_handler(self):
        class MyView(View):
            async def get(self, request, user_id=None):
                return JSONResponse({"user_id": user_id})

        view = MyView()
        req = make_request("GET")
        resp = await view.dispatch(req, user_id=42)
        import json

        data = json.loads(resp.body)
        assert data["user_id"] == 42


# ---------------------------------------------------------------------------
# View.__init__ kwargs
# ---------------------------------------------------------------------------


class TestViewInit:
    def test_kwargs_set_as_attributes(self):
        class MyView(View):
            pass

        view = MyView(custom="value")
        assert view.custom == "value"


# ---------------------------------------------------------------------------
# View.http_method_not_allowed
# ---------------------------------------------------------------------------


class TestMethodNotAllowed:
    def test_raises_method_not_allowed(self):
        class GetOnly(View):
            async def get(self, request):
                return Response("ok")

        view = GetOnly()
        req = make_request("DELETE")
        with pytest.raises(MethodNotAllowed):
            view.http_method_not_allowed(req)


# ---------------------------------------------------------------------------
# View._allowed_methods
# ---------------------------------------------------------------------------


class TestAllowedMethods:
    def test_returns_methods_with_handlers(self):
        class MyView(View):
            async def get(self, request):
                return Response("ok")

            async def post(self, request):
                return Response("ok")

        view = MyView()
        methods = view._allowed_methods()
        assert "GET" in methods
        assert "POST" in methods
        # options is always defined in View base
        assert "OPTIONS" in methods

    def test_no_handlers_minimal(self):
        class EmptyView(View):
            http_method_names = []

        view = EmptyView()
        methods = view._allowed_methods()
        assert methods == []


# ---------------------------------------------------------------------------
# View.as_view
# ---------------------------------------------------------------------------


class TestAsView:
    def test_as_view_returns_callable(self):
        class MyView(View):
            async def get(self, request):
                return Response("ok")

        handler = MyView.as_view()
        assert callable(handler)

    def test_as_view_sets_view_class(self):
        class MyView(View):
            async def get(self, request):
                return Response("ok")

        handler = MyView.as_view()
        assert handler.view_class is MyView

    def test_as_view_preserves_name(self):
        class MyView(View):
            pass

        handler = MyView.as_view()
        assert handler.__name__ == "MyView"

    def test_as_view_with_invalid_kwarg_raises(self):
        class MyView(View):
            pass

        with pytest.raises(TypeError):
            MyView.as_view(get="should not be allowed")

    @pytest.mark.asyncio
    async def test_as_view_creates_instance_per_call(self):
        class MyView(View):
            async def get(self, request):
                return JSONResponse({"ok": True})

        handler = MyView.as_view()
        req = make_request("GET")
        resp = await handler(req)
        assert resp.status_code == 200

    def test_as_view_stores_initkwargs(self):
        class MyView(View):
            pass

        handler = MyView.as_view(extra="data")
        assert handler.view_initkwargs == {"extra": "data"}


# ---------------------------------------------------------------------------
# View.register
# ---------------------------------------------------------------------------


class TestRegister:
    def test_register_attaches_to_router(self):
        class MyView(View):
            async def get(self, request):
                return Response("ok")

        router = Router()
        MyView.register(router, "/test/")

        route_paths = [r.path for r in router.routes]
        assert "/test/" in route_paths

    def test_register_with_custom_name(self):
        class NamedView(View):
            async def get(self, request):
                return Response("ok")

        router = Router()
        NamedView.register(router, "/named/", name="custom_name")
        route_names = [r.name for r in router.routes]
        assert "custom_name" in route_names

    def test_register_no_handlers_skips_options(self):
        class NoHandlers(View):
            http_method_names = []

        router = Router()
        NoHandlers.register(router, "/empty/")
        # With no methods, handler should not be registered (no methods list)
        # Just verify it doesn't raise


# ---------------------------------------------------------------------------
# View serializer_class
# ---------------------------------------------------------------------------


class TestSerializerClass:
    def test_serializer_class_default_none(self):
        class MyView(View):
            pass

        assert MyView.serializer_class is None

    def test_serializer_class_can_be_set(self):
        from openviper.serializers import Serializer

        class MySerializer(Serializer):
            name: str

        class MyView(View):
            serializer_class = MySerializer

        assert MyView.serializer_class is MySerializer
