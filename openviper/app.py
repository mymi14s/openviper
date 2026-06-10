"""OpenViper ASGI application.

The central ``OpenViper`` class is the entry point for all request handling.
It ties together routing, middleware, dependency injection, exception handling,
and OpenAPI schema generation.
"""

from __future__ import annotations

import functools
import html
import importlib
import inspect
import json
import logging
import os
import typing
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, cast

from openviper.conf import settings
from openviper.contrib.default.middleware import DefaultLandingMiddleware
from openviper.core.context import current_request, current_router
from openviper.debug.traceback_page import render_debug_page
from openviper.exceptions import FieldError, HTTPException, NotFound, QueryError, TableNotFound
from openviper.http.request import Request
from openviper.http.response import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from openviper.middleware.base import ASGIApp, MiddlewareEntry, build_middleware_stack
from openviper.middleware.cors import CORSMiddleware
from openviper.middleware.error import ServerErrorMiddleware
from openviper.openapi.router import should_register_openapi
from openviper.openapi.schema import filter_openapi_routes, generate_openapi_schema
from openviper.openapi.ui import get_redoc_html, get_swagger_html
from openviper.routing.router import Router, include
from openviper.staticfiles.handlers import StaticFilesMiddleware, discover_app_static_dirs
from openviper.utils.logging import get_uvicorn_log_config
from openviper.version import __version__

if TYPE_CHECKING:
    import httpx

    from openviper.http.types import ASGIReceive, ASGIScope, ASGISend

try:
    from pydantic import BaseModel as PydanticBaseModel

    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False

logger = logging.getLogger("openviper.app")


@functools.lru_cache(maxsize=128)
def get_handler_signature(
    handler: Callable[..., object],
) -> tuple[inspect.Signature, dict[str, object]]:
    """Return ``(signature, type_hints)`` for *handler*, cached by identity.

    Bounded by ``maxsize=128`` - sufficient for most realistic apps
    while reducing memory overhead.
    """
    sig = inspect.signature(handler)
    try:
        hints: dict[str, object] = typing.get_type_hints(handler)
    except Exception:
        hints = {}
    return sig, hints


def resolve_middleware_entry(mw: object) -> object:
    """Import and return a middleware class from a dotted string, or pass through as-is.

    Raises ``ImportError`` if *mw* is a string that cannot be imported.
    """
    if not isinstance(mw, str):
        return mw
    try:
        module_path, class_name = mw.rsplit(".", 1)
        mod = importlib.import_module(module_path)
        return getattr(mod, class_name)
    except (ImportError, AttributeError) as exc:
        raise ImportError(f"Could not load middleware {mw!r}: {exc}") from exc


class OpenViper:
    """The OpenViper ASGI application.

    This class acts as both an ASGI callable **and** a router decorator,
    so routes are registered directly on the app instance.

    Args:
        debug: Enable debug mode (overrides settings.DEBUG when set).
        middleware: Extra middleware to prepend to the stack.
        title: OpenAPI document title.
        version: API version string.
        openapi_url: URL to serve the OpenAPI JSON schema.
        docs_url: URL for Swagger UI.
        redoc_url: URL for ReDoc UI.
    """

    __slots__ = (
        "debug",
        "title",
        "description",
        "version",
        "openapi_url",
        "docs_url",
        "redoc_url",
        "router",
        "_extra_middleware",
        "_exception_handlers",
        "_startup_handlers",
        "_shutdown_handlers",
        "_started_apps",
        "_openapi_schema",
        "_middleware_app",
        "_state",
        "_handler_param_cache",
    )

    def __init__(
        self,
        debug: bool | None = None,
        middleware: list[MiddlewareEntry] | None = None,
        title: str | None = None,
        version: str | None = None,
        description: str | None = None,
        openapi_url: str | None = None,
        docs_url: str | None = None,
        redoc_url: str | None = None,
    ) -> None:
        self.debug = debug if debug is not None else getattr(settings, "DEBUG", True)

        if self.debug and os.environ.get("ENVIRONMENT") in ("production", "prod"):
            logger.warning(
                "DEBUG mode is enabled in a production environment. "
                "This exposes sensitive information and should be disabled."
            )
        self.title = cast("str", title or settings.OPENAPI.get("title", "OpenViper API"))
        self.version = cast("str", version or settings.OPENAPI.get("version", "3.0.0"))
        self.description = cast("str", description or settings.OPENAPI.get("description", ""))
        self.openapi_url = cast(
            "str",
            openapi_url or settings.OPENAPI.get("schema_url", "/open-api/openapi.json"),
        )
        self.docs_url = cast("str", docs_url or settings.OPENAPI.get("docs_url", "/open-api/docs"))
        self.redoc_url = cast(
            "str", redoc_url or settings.OPENAPI.get("redoc_url", "/open-api/redoc")
        )

        self.router = Router()
        self._extra_middleware: list[MiddlewareEntry] = middleware or []
        self._exception_handlers: dict[type[Exception], Callable[..., Awaitable[Response]]] = {}
        self._startup_handlers: list[Callable[[], Awaitable[None] | None]] = []
        self._shutdown_handlers: list[Callable[[], Awaitable[None] | None]] = []
        self._started_apps: list[str] = []
        self._openapi_schema: dict[str, object] | None = None
        self._middleware_app: ASGIApp | None = None
        self._state: dict[str, object] = {}
        self._handler_param_cache: dict[object, dict[str, object]] = {}

        if should_register_openapi():
            self._register_openapi_routes()

        self._autodiscover_routes()

    def get(self, path: str, **kwargs: object) -> Callable[..., object]:
        return self.router.get(path, **kwargs)

    def post(self, path: str, **kwargs: object) -> Callable[..., object]:
        return self.router.post(path, **kwargs)

    def put(self, path: str, **kwargs: object) -> Callable[..., object]:
        return self.router.put(path, **kwargs)

    def patch(self, path: str, **kwargs: object) -> Callable[..., object]:
        return self.router.patch(path, **kwargs)

    def delete(self, path: str, **kwargs: object) -> Callable[..., object]:
        return self.router.delete(path, **kwargs)

    def options(self, path: str, **kwargs: object) -> Callable[..., object]:
        return self.router.options(path, **kwargs)

    def route(self, path: str, methods: list[str], **kwargs: object) -> Callable[..., object]:
        return self.router.route(path, methods, **kwargs)

    def include_router(self, router: Router, prefix: str = "") -> None:
        """Mount a sub-router.

        Args:
            router: The Router to mount.
            prefix: Optional prefix to prepend to all routes.
        """
        if prefix:
            self.router.include_router(include(router, prefix=prefix))
        else:
            self.router.include_router(router)

    def _autodiscover_routes(self) -> None:
        """Auto-discover and register route_paths from the project routes module.

        Derives the routes module from the ``OPENVIPER_SETTINGS_MODULE`` env var
        by using the top-level package and importing ``route_paths`` from
        ``<project_package>.routes``.
        """
        settings_module = os.environ.get("OPENVIPER_SETTINGS_MODULE", "")
        if not settings_module:
            return

        # Derive the routes module from the top-level package.
        # e.g. "project.settings"       -> "project.routes"
        #      "project.settings.prod"   -> "project.routes"
        #      "settings"               -> skip (no package prefix)
        top_package = settings_module.split(".")[0]
        if top_package == settings_module:
            # Bare module name with no package - cannot derive routes path.
            return
        routes_module_path = f"{top_package}.routes"

        try:
            routes_module = importlib.import_module(routes_module_path)
        except ModuleNotFoundError as exc:
            if exc.name == routes_module_path:
                # The routes module itself simply does not exist - nothing to register.
                logger.debug(
                    "No routes module found at %s - skipping auto-discovery.",
                    routes_module_path,
                )
                return
            # A nested import inside the routes module failed - always re-raise so
            # developers see a clear error instead of silent 404s for every route.
            raise

        route_paths: list[tuple[str, Router]] = getattr(routes_module, "route_paths", [])
        for prefix, router in route_paths:
            self.include_router(router, prefix=prefix)

        logger.debug(
            "Auto-registered %d router(s) from %s.",
            len(route_paths),
            routes_module_path,
        )

    async def _call_installed_app_ready_hooks(self) -> None:
        """Call ``ready()`` on every installed app that exposes one.

        For each entry in ``settings.INSTALLED_APPS`` OpenViper looks for a
        ``ready`` callable in two places, in order:

        1. ``<app>.ready`` - a top-level attribute on the app package
           (i.e. defined in ``<app>/__init__.py``).
        2. ``<app>.apps.ready`` - a ``ready`` attribute inside an ``apps``
           sub-module (useful when plugin authors prefer keeping startup
           logic separate).

        The callable may be either a plain function **or** a coroutine
        function - both are supported.
        """
        for app_label in getattr(settings, "INSTALLED_APPS", ()):
            hook: object | None = None

            try:
                mod = importlib.import_module(app_label)
                hook = getattr(mod, "ready", None)
            except ImportError as exc:
                raise RuntimeError(
                    f"INSTALLED_APPS: could not import {app_label!r}. "
                    f"Ensure the package is installed and the name is correct."
                ) from exc

            if hook is None:
                try:
                    apps_mod = importlib.import_module(f"{app_label}.apps")
                    hook = getattr(apps_mod, "ready", None)
                except ImportError:
                    pass

            if hook is None:
                try:
                    lifecycle_mod = importlib.import_module(f"{app_label}.lifecycle")
                    hook = getattr(lifecycle_mod, "ready", None)
                except ImportError:
                    pass

            if hook is None or not callable(hook):
                continue

            try:
                result = hook()
                if inspect.isawaitable(result):
                    await result
                logger.debug("Called ready() for installed app %r.", app_label)
            except Exception as exc:
                raise RuntimeError(
                    f"ready() for installed app {app_label!r} raised an error: {exc}"
                ) from exc

    async def _call_installed_app_startup_hooks(self) -> None:
        """Call ``startup()`` from installed app ``lifecycle.py`` modules."""
        self._started_apps.clear()
        for app_label in getattr(settings, "INSTALLED_APPS", ()):
            try:
                lifecycle_mod = importlib.import_module(f"{app_label}.lifecycle")
            except ModuleNotFoundError as exc:
                if exc.name == f"{app_label}.lifecycle":
                    continue
                raise

            hook = getattr(lifecycle_mod, "startup", None)
            if hook is None or not callable(hook):
                continue

            try:
                result = hook()
                if inspect.isawaitable(result):
                    await result
                logger.debug("Called startup() for installed app %r.", app_label)
            except Exception as exc:
                await self._call_installed_app_shutdown_hooks()
                raise RuntimeError(
                    f"startup() for installed app {app_label!r} raised an error: {exc}"
                ) from exc
            self._started_apps.append(app_label)

    async def _call_installed_app_shutdown_hooks(self) -> None:
        """Call ``shutdown()`` for started lifecycle apps in reverse order."""
        errors: list[tuple[str, Exception]] = []
        for app_label in reversed(self._started_apps):
            try:
                lifecycle_mod = importlib.import_module(f"{app_label}.lifecycle")
            except ModuleNotFoundError as exc:
                if exc.name == f"{app_label}.lifecycle":
                    continue
                raise

            hook = getattr(lifecycle_mod, "shutdown", None)
            if hook is None or not callable(hook):
                continue

            try:
                result = hook()
                if inspect.isawaitable(result):
                    await result
                logger.debug("Called shutdown() for installed app %r.", app_label)
            except Exception as exc:
                logger.error(
                    "shutdown() for installed app %r raised an error: %s",
                    app_label,
                    exc,
                    exc_info=True,
                )
                errors.append((app_label, exc))

        self._started_apps.clear()
        if errors:
            details = "; ".join(f"{app_label}: {exc}" for app_label, exc in errors)
            raise RuntimeError(f"{len(errors)} shutdown hook(s) failed: {details}")

    def on_startup(self, func: Callable[..., object]) -> Callable[..., object]:
        """Register a startup handler."""
        self._startup_handlers.append(func)
        return func

    def on_shutdown(self, func: Callable[..., object]) -> Callable[..., object]:
        """Register a shutdown handler."""
        self._shutdown_handlers.append(func)
        return func

    def exception_handler(self, exc_class: type[Exception]) -> Callable[..., object]:
        """Decorator to register a custom exception handler."""

        def decorator(func: Callable[..., object]) -> Callable[..., object]:
            self._exception_handlers[exc_class] = func
            return func

        return decorator

    def _register_openapi_routes(self) -> None:
        """Register /open-api/openapi.json, /open-api/docs, /open-api/redoc routes."""

        @self.router.get(self.openapi_url, name="openapi_schema")
        async def openapi_schema_handler(request: Request) -> Response:
            schema = self.get_openapi_schema()
            return Response(
                json.dumps(schema, indent=2).encode(),
                media_type="application/json",
            )

        @self.router.get(self.docs_url, name="swagger_ui")
        async def swagger_ui_handler(request: Request) -> Response:
            html = get_swagger_html(
                title=self.title,
                openapi_url=self.openapi_url,
            )
            return HTMLResponse(html)

        @self.router.get(self.redoc_url, name="redoc_ui")
        async def redoc_handler(request: Request) -> Response:
            html = get_redoc_html(title=self.title, openapi_url=self.openapi_url)
            return HTMLResponse(html)

    def get_openapi_schema(self) -> dict[str, object]:
        if self._openapi_schema is None:
            filtered = filter_openapi_routes(self.router.routes)
            self._openapi_schema = generate_openapi_schema(
                routes=filtered,
                title=self.title,
                version=self.version,
                description=self.description,
            )
        return self._openapi_schema

    def invalidate_openapi_schema(self) -> None:
        """Force schema regeneration on next request."""
        self._openapi_schema = None

    def invalidate_middleware_cache(self) -> None:
        """Invalidate middleware stack cache to rebuild on next request.

        Useful when routes are added dynamically after initial setup.
        """
        self._middleware_app = None

    def _get_middleware_app(self) -> ASGIApp:
        if self._middleware_app is None:
            self._middleware_app = self._build_middleware_stack()
        return self._middleware_app

    def _build_middleware_stack(self) -> ASGIApp:
        raw_middleware: list[MiddlewareEntry] = []

        for mw_path in getattr(settings, "MIDDLEWARE", []):
            raw_middleware.append(resolve_middleware_entry(mw_path))

        resolved_middleware = self.resolve_middleware(raw_middleware)

        app = build_middleware_stack(self._core_app, resolved_middleware)

        has_custom_root = self._has_custom_root_route()
        app = DefaultLandingMiddleware(
            app,
            debug=self.debug,
            version=__version__,
            has_custom_root=has_custom_root,
        )

        app = ServerErrorMiddleware(app, debug=self.debug)

        app = self._add_static_file_serving(app)

        return app

    def resolve_middleware(self, raw_middleware: list[MiddlewareEntry]) -> list[MiddlewareEntry]:
        """Resolve middleware entries, wiring CORS settings when applicable."""
        resolved: list[MiddlewareEntry] = []
        for mw in list(self._extra_middleware) + raw_middleware:
            cls = resolve_middleware_entry(mw)
            if cls is CORSMiddleware:
                resolved.append((cls, self.cors_kwargs()))
            else:
                resolved.append(cls)

        if getattr(settings, "RATE_LIMIT_REQUESTS", 0) > 0:
            cls = resolve_middleware_entry("openviper.middleware.ratelimit.RateLimitMiddleware")
            resolved.insert(0, cls)

        return resolved

    @staticmethod
    def cors_kwargs() -> dict[str, object]:
        """Build keyword arguments for CORSMiddleware from settings."""
        return {
            "allowed_origins": list(getattr(settings, "CORS_ALLOWED_ORIGINS", None) or ["*"]),
            "allow_credentials": getattr(settings, "CORS_ALLOW_CREDENTIALS", False),
            "allowed_methods": list(getattr(settings, "CORS_ALLOWED_METHODS", None) or ["*"]),
            "allowed_headers": list(getattr(settings, "CORS_ALLOWED_HEADERS", None) or ["*"]),
            "expose_headers": list(getattr(settings, "CORS_EXPOSE_HEADERS", None) or []),
            "max_age": getattr(settings, "CORS_MAX_AGE", 600),
        }

    def _add_static_file_serving(self, app: ASGIApp) -> ASGIApp:
        """Wrap the app with static and media file serving in DEBUG mode.

        Both ``self.debug`` and the ``ENVIRONMENT`` variable are checked so
        that static serving is never accidentally enabled in production.
        """
        env = os.environ.get("ENVIRONMENT", "").lower()
        if not self.debug or env in ("production", "prod"):
            return app

        static_url = getattr(settings, "STATIC_URL", "/static/").rstrip("/")
        static_root = getattr(settings, "STATIC_ROOT", "static")

        discovered = [str(d) for d in discover_app_static_dirs()]
        if static_root not in discovered:
            discovered.append(static_root)

        app = StaticFilesMiddleware(app, url_path=static_url, directories=discovered)
        logger.debug("StaticFilesMiddleware enabled for %s", static_url)

        media_url = getattr(settings, "MEDIA_URL", "/media/").rstrip("/")
        media_root = getattr(settings, "MEDIA_ROOT", "media")

        app = StaticFilesMiddleware(app, url_path=media_url, directories=[media_root])
        logger.debug("Media serving enabled for %s → %s", media_url, media_root)

        return app

    def _has_custom_root_route(self) -> bool:
        """Check if the user has defined a GET / route (excluding OpenAPI routes)."""
        openapi_names = {"openapi_schema", "swagger_ui", "redoc_ui"}
        for route in self.router.routes:
            if getattr(route, "path", "") in ("/", "") and "GET" in getattr(route, "methods", []):
                name = getattr(route, "name", "")
                if name not in openapi_names:
                    return True
        return False

    async def _core_app(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        """Resolve route and call the handler (inner ASGI callable)."""
        if scope["type"] == "lifespan":
            await self._handle_lifespan(scope, receive, send)
            return

        if scope["type"] == "http":
            await self._handle_http(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await self._handle_unrouted_websocket(receive, send)
            return

    async def _handle_unrouted_websocket(self, receive: ASGIReceive, send: ASGISend) -> None:
        """Close any WebSocket connection that reaches the core app unhandled.

        Plugins that handle WebSocket must be added as middleware so they
        intercept the scope before it reaches this point.  If none do, the
        connection is closed cleanly rather than silently dropped.
        """
        event = await receive()
        if event.get("type") == "websocket.connect":
            await send({"type": "websocket.close", "code": 4404})

    async def _handle_http(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        request = Request(scope, receive)
        request.user = scope.get("user")
        request.auth = scope.get("auth")

        token = current_request.set(request)
        router_token = current_router.set(self.router)
        try:
            route, path_params = self.router.resolve(request.method, request.path)
            request.path_params = path_params

            handler = route.handler
            for mw in reversed(route.middlewares):
                handler = mw(handler)

            response = await self.call_handler(handler, request)
        except NotFound as exc:
            response = self._try_append_slash_redirect(request) or await self._handle_exception(
                request, exc
            )
        except Exception as exc:
            response = await self._handle_exception(request, exc)
        finally:
            current_request.reset(token)
            current_router.reset(router_token)

        await response(scope, receive, send)

    async def call_handler(self, handler: Callable[..., object], request: Request) -> Response:
        """Call a view handler, performing automatic response coercion."""
        # Handler object as cache key avoids id() collisions.
        if handler not in self._handler_param_cache:
            sig, hints = get_handler_signature(handler)
            params = sig.parameters
            param_mapping: dict[str, object] = {"params": {}, "has_var_keyword": False}

            for name, param in params.items():
                annotation = hints.get(name, param.annotation)

                # Determine if this parameter expects the Request object
                is_request_param = (
                    name in ("request", "req")
                    or annotation is Request
                    or (isinstance(annotation, type) and issubclass(annotation, Request))
                    or annotation is inspect.Parameter.empty
                    or (isinstance(annotation, str) and annotation.lower() in ("request", "req"))
                )

                param_mapping["params"][name] = {
                    "is_request": is_request_param,
                    "is_var_keyword": param.kind == inspect.Parameter.VAR_KEYWORD,
                }

                if param.kind == inspect.Parameter.VAR_KEYWORD:
                    param_mapping["has_var_keyword"] = True

            self._handler_param_cache[handler] = param_mapping

        param_mapping = self._handler_param_cache[handler]
        kwargs: dict[str, object] = {}

        for name, info in param_mapping["params"].items():
            if info["is_request"] and name not in request.path_params:
                kwargs[name] = request
            elif name in request.path_params:
                kwargs[name] = request.path_params[name]
            elif info["is_var_keyword"]:
                for p_name, p_value in request.path_params.items():
                    if p_name not in kwargs:
                        kwargs[p_name] = p_value

        result = handler(**kwargs)
        if inspect.isawaitable(result):
            result = await result

        return self.coerce_response(result)

    def coerce_response(self, result: object) -> Response:
        """Convert a handler's return value to a proper Response."""
        if isinstance(result, Response):
            return result

        if isinstance(result, (dict, list)):
            return JSONResponse(result)
        if result is None:
            return Response(b"", status_code=204)
        if isinstance(result, (str, bytes)):
            return PlainTextResponse(result)
        if HAS_PYDANTIC and isinstance(result, PydanticBaseModel):
            return JSONResponse(result.model_dump())
        if hasattr(result, "model_dump") and callable(result.model_dump):
            return JSONResponse(result.model_dump())
        return JSONResponse(result)

    def _try_append_slash_redirect(self, request: Request) -> RedirectResponse | None:
        """Return a 301 redirect to ``path + "/"`` in production when the route exists.

        Only active when ``settings.DEBUG`` is falsy and the request path does
        not already end with a slash.  Returns ``None`` when the slash-appended
        path still does not resolve, so the caller can fall through to normal
        error handling.

        The redirect target is validated to prevent open-redirect attacks by
        ensuring the resulting URL remains a same-origin, relative path.
        """
        if settings.DEBUG:
            return None
        path = request.path
        if path.endswith("/"):
            return None
        # Reject paths containing directory-traversal sequences.
        if ".." in path:
            return None
        slash_path = path + "/"
        # Ensure the slash-appended path is still a safe relative path.
        if not slash_path.startswith("/") or "//" in slash_path:
            return None
        try:
            self.router.resolve(request.method, slash_path)
        except Exception:
            return None
        qs = request.query_string
        location = slash_path + (f"?{qs.decode()}" if qs else "")
        return RedirectResponse(location, status_code=301)

    async def _handle_exception(self, request: Request, exc: Exception) -> Response:
        """Dispatch to the appropriate exception handler or return generic error."""
        # Walk the MRO to find the most specific registered handler
        for exc_type in type(exc).__mro__:
            if exc_type in self._exception_handlers:
                handler = self._exception_handlers[exc_type]
                result: object = handler(request, exc)
                if inspect.isawaitable(result):
                    result = await result
                return self.coerce_response(result)

        if isinstance(exc, HTTPException):
            return self._create_error_response(
                request,
                {"detail": exc.detail},
                status_code=exc.status_code,
                headers=exc.headers,
            )

        if isinstance(exc, TableNotFound):
            # In production, avoid leaking internal table/model names.
            detail = (
                str(exc)
                if self.debug
                else "Requested resource not found. Run migrations if needed."
            )
            return self._create_error_response(
                request,
                {"error": "TableNotFound", "detail": detail},
                status_code=503,
            )

        if isinstance(exc, (FieldError, QueryError)):
            # In production, avoid leaking internal field names or query structure.
            detail = str(exc) if self.debug else "Invalid request parameters."
            return self._create_error_response(
                request,
                {"error": type(exc).__name__, "detail": detail},
                status_code=400,
            )

        logger.exception("Unhandled exception: %s", exc)
        if self.debug:
            return HTMLResponse(render_debug_page(exc, request), status_code=500)
        return self._create_error_response(
            request, {"detail": "Internal Server Error"}, status_code=500
        )

    def _create_error_response(
        self,
        request: Request,
        content: dict[str, object],
        status_code: int,
        headers: dict[str, str] | None = None,
    ) -> Response:
        """Create an error response (HTML or JSON) based on the Accept header."""
        accept = request.headers.get("accept", "")
        if accept and "text/html" in accept:
            # Simple HTML error page with XSS protection
            title = html.escape(str(content.get("detail", "Error")))
            html_content = f"<html><head><title>{title}</title></head><body>"
            html_content += f"<h1>{status_code} {title}</h1>"
            if self.debug and "traceback" in content:
                exc_type = html.escape(str(content.get("type", "Exception")))
                html_content += f"<h3>{exc_type}</h3>"
                # Escape traceback lines for XSS protection
                escaped_tb = [html.escape(line) for line in content["traceback"]]
                html_content += "<pre>" + "\n".join(escaped_tb) + "</pre>"
            html_content += "</body></html>"
            return HTMLResponse(html_content, status_code=status_code, headers=headers)

        return JSONResponse(content, status_code=status_code, headers=headers)

    async def _handle_lifespan(
        self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend
    ) -> None:
        """ASGI lifespan events: startup and shutdown."""
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                try:
                    self._get_middleware_app()

                    if should_register_openapi():
                        self.get_openapi_schema()

                    await self._call_installed_app_ready_hooks()

                    await self._call_installed_app_startup_hooks()

                    for handler in self._startup_handlers:
                        result = handler()
                        if inspect.isawaitable(result):
                            await result
                    await send({"type": "lifespan.startup.complete"})
                except Exception as exc:
                    await send({"type": "lifespan.startup.failed", "message": str(exc)})
                    return

            elif message["type"] == "lifespan.shutdown":
                try:
                    await self._call_installed_app_shutdown_hooks()
                    for handler in self._shutdown_handlers:
                        result = handler()
                        if inspect.isawaitable(result):
                            await result
                    await send({"type": "lifespan.shutdown.complete"})
                except Exception as exc:
                    await send({"type": "lifespan.shutdown.failed", "message": str(exc)})
                break  # exit the lifespan event loop

    async def __call__(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        app = self._get_middleware_app()
        await app(scope, receive, send)

    def run(
        self,
        host: str = "127.0.0.1",
        port: int = 8000,
        reload: bool = True,
        log_level: str = "info",
        workers: int = 1,
    ) -> None:
        """Start a uvicorn development server.

        Prefer using ``python viperctl.py start-server`` for project use.

        Args:
            host: Bind address.
            port: Bind port.
            reload: Enable auto-reload on code changes.
            log_level: Uvicorn log level string.
            workers: Number of worker processes (reload must be False).
        """

        uvicorn_module = importlib.import_module("uvicorn")
        uvicorn_run = uvicorn_module.run
        uvicorn_run(
            self,
            host=host,
            port=port,
            reload=reload,
            log_level=log_level,
            workers=workers if not reload else 1,
            log_config=get_uvicorn_log_config(),
        )

    def test_client(self, **kwargs: object) -> httpx.AsyncClient:
        """Return an httpx.AsyncClient configured for this app.

        The returned client must be used as an async context manager
        to ensure proper cleanup of resources.
        """
        base_url = kwargs.pop("base_url", "http://testserver")
        httpx_module = importlib.import_module("httpx")
        transport = httpx_module.ASGITransport(app=self)
        return cast(
            "httpx.AsyncClient",
            httpx_module.AsyncClient(
                transport=transport,
                base_url=base_url,
                **kwargs,
            ),
        )

    def __repr__(self) -> str:
        return f"OpenViper(title={self.title!r}, routes={len(self.router.routes)})"
