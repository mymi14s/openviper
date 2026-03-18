"""OpenViper ASGI application.

The central ``OpenViper`` class is the entry point for all request handling.
It ties together routing, middleware, dependency injection, exception handling,
and OpenAPI schema generation.

Example:
    .. code-block:: python

        from openviper import OpenViper

        app = OpenViper()

        @app.get("/")
        async def hello(request):
            return {"message": "Hello, World!"}
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import html
import importlib
import inspect
import json
import logging
import os
import traceback
import typing
from collections.abc import Awaitable, Callable
from typing import Any, cast

import httpx
import uvicorn

from openviper.conf import settings
from openviper.contrib.default.middleware import DefaultLandingMiddleware
from openviper.core.context import current_request
from openviper.exceptions import HTTPException
from openviper.http.request import Request
from openviper.http.response import HTMLResponse, JSONResponse, PlainTextResponse, Response
from openviper.middleware.base import ASGIApp, build_middleware_stack
from openviper.middleware.cors import CORSMiddleware
from openviper.openapi.schema import generate_openapi_schema
from openviper.openapi.ui import get_redoc_html, get_swagger_html
from openviper.routing.router import Router, include

logger = logging.getLogger("openviper.app")

# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=128)
def _get_handler_signature(
    handler: Callable[..., Any],
) -> tuple[inspect.Signature, dict[str, Any]]:
    """Return ``(signature, type_hints)`` for *handler*, cached by identity.

    Bounded by ``maxsize=128`` — sufficient for most realistic apps
    while reducing memory overhead.
    """
    sig = inspect.signature(handler)
    try:
        hints: dict[str, Any] = typing.get_type_hints(handler)
    except Exception:
        hints = {}
    return sig, hints


def _resolve_middleware_entry(mw: Any, critical: bool = False) -> Any | None:
    """Import and return a middleware class from a dotted string, or pass through as-is.

    Returns ``None`` and logs a warning if the import fails.
    Raises ImportError if critical=True and import fails.
    """
    if not isinstance(mw, str):
        return mw
    try:
        module_path, class_name = mw.rsplit(".", 1)
        mod = importlib.import_module(module_path)
        return getattr(mod, class_name)
    except (ImportError, AttributeError) as exc:
        if critical:
            logger.error("Failed to load critical middleware %s: %s", mw, exc)
            raise ImportError(f"Critical middleware {mw} could not be loaded: {exc}") from exc
        logger.warning("Could not load middleware %s: %s", mw, exc)
        return None


class OpenViper:
    """The OpenViper ASGI application.

    This class acts as both an ASGI callable **and** a router decorator,
    so you can register routes directly on the app instance.

    Args:
        debug: Enable debug mode (overrides settings.DEBUG when set).
        middleware: Extra middleware to prepend to the stack.
        title: OpenAPI document title.
        version: API version string.
        openapi_url: URL to serve the OpenAPI JSON schema.
        docs_url: URL for Swagger UI.
        redoc_url: URL for ReDoc UI.

    Example:
        >>> app = OpenViper(title="My API", version="1.0.0")
        >>> @app.get("/ping")
        ... async def ping(request):
        ...     return {"pong": True}
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
        "_openapi_schema",
        "_middleware_app",
        "_state",
        "_handler_param_cache",
    )

    def __init__(
        self,
        debug: bool | None = None,
        middleware: list[Any] | None = None,
        title: str | None = None,
        version: str | None = None,
        openapi_url: str | None = None,
        docs_url: str | None = None,
        redoc_url: str | None = None,
    ) -> None:
        self.debug = debug if debug is not None else getattr(settings, "DEBUG", True)

        # Warn if debug mode is enabled in production-like environments
        if self.debug and os.environ.get("ENVIRONMENT") in ("production", "prod"):
            logger.warning(
                "DEBUG mode is enabled in a production environment. "
                "This exposes sensitive information and should be disabled."
            )
        self.title = cast("str", title or getattr(settings, "OPENAPI_TITLE", "OpenViper API"))
        self.version = cast("str", version or getattr(settings, "OPENAPI_VERSION", "3.0.0"))
        self.openapi_url = cast(
            "str",
            openapi_url or getattr(settings, "OPENAPI_SCHEMA_URL", "/open-api/openapi.json"),
        )
        self.docs_url = cast(
            "str", docs_url or getattr(settings, "OPENAPI_DOCS_URL", "/open-api/docs")
        )
        self.redoc_url = cast(
            "str", redoc_url or getattr(settings, "OPENAPI_REDOC_URL", "/open-api/redoc")
        )

        self.router = Router()
        self._extra_middleware: list[Any] = middleware or []
        self._exception_handlers: dict[type[Exception], Callable[..., Awaitable[Response]]] = {}
        self._startup_handlers: list[Callable[[], Awaitable[None] | None]] = []
        self._shutdown_handlers: list[Callable[[], Awaitable[None] | None]] = []
        self._openapi_schema: dict[str, Any] | None = None
        self._middleware_app: ASGIApp | None = None
        self._state: dict[str, Any] = {}
        self._handler_param_cache: dict[int, dict[str, Any]] = {}

        # Register internal routes (schema, docs)
        if getattr(settings, "OPENAPI_ENABLED", True):
            self._register_openapi_routes()

    # ── Route registration (delegate to router) ───────────────────────────

    def get(self, path: str, **kwargs: Any) -> Callable[..., Any]:
        return self.router.get(path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Callable[..., Any]:
        return self.router.post(path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Callable[..., Any]:
        return self.router.put(path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Callable[..., Any]:
        return self.router.patch(path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Callable[..., Any]:
        return self.router.delete(path, **kwargs)

    def options(self, path: str, **kwargs: Any) -> Callable[..., Any]:
        return self.router.options(path, **kwargs)

    def route(self, path: str, methods: list[str], **kwargs: Any) -> Callable[..., Any]:
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

    # ── Lifecycle hooks ───────────────────────────────────────────────────

    def on_startup(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """Register a startup handler."""
        self._startup_handlers.append(func)
        return func

    def on_shutdown(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """Register a shutdown handler."""
        self._shutdown_handlers.append(func)
        return func

    # ── Exception handlers ────────────────────────────────────────────────

    def exception_handler(self, exc_class: type[Exception]) -> Callable[..., Any]:
        """Decorator to register a custom exception handler.

        Example:
            >>> @app.exception_handler(ValueError)
            ... async def handle_value_error(request, exc):
            ...     return JSONResponse({"error": str(exc)}, status_code=400)
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self._exception_handlers[exc_class] = func
            return func

        return decorator

    # ── OpenAPI ───────────────────────────────────────────────────────────

    def _register_openapi_routes(self) -> None:
        """Register /open-api/openapi.json, /open-api/docs, /open-api/redoc routes."""
        # Use add() to bypass prefix-stripping issues if any, or just use literal

        @self.router.get(self.openapi_url, name="openapi_schema")
        async def openapi_schema_handler(request: Request) -> Response:
            schema = self._get_openapi_schema()
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

    def _get_openapi_schema(self) -> dict[str, Any]:
        if self._openapi_schema is None:
            self._openapi_schema = generate_openapi_schema(
                routes=self.router.routes,
                title=self.title,
                version=self.version,
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

    # ── Middleware stack ──────────────────────────────────────────────────

    def _get_middleware_app(self) -> ASGIApp:
        if self._middleware_app is None:
            self._middleware_app = self._build_middleware_stack()
        return self._middleware_app

    def _build_middleware_stack(self) -> ASGIApp:
        raw_middleware: list[Any] = []

        # Define critical middleware that must load successfully
        critical_middleware = getattr(settings, "CRITICAL_MIDDLEWARE", [])

        # Load from settings — resolve strings immediately.
        for mw_path in getattr(settings, "MIDDLEWARE", []):
            is_critical = mw_path in critical_middleware
            cls = _resolve_middleware_entry(mw_path, critical=is_critical)
            if cls is not None:
                raw_middleware.append(cls)

        # Prepend extra middleware passed at construction (already classes or strings).
        resolved_middleware: list[Any] = []
        for mw in list(self._extra_middleware) + raw_middleware:
            cls = _resolve_middleware_entry(mw, critical=False)
            if cls is not None:
                if cls is CORSMiddleware:
                    # Wire CORS settings from settings.py into the middleware instance.
                    cors_kwargs: dict[str, Any] = {
                        "allowed_origins": list(
                            getattr(settings, "CORS_ALLOWED_ORIGINS", None) or ["*"]
                        ),
                        "allow_credentials": getattr(settings, "CORS_ALLOW_CREDENTIALS", False),
                        "allowed_methods": list(
                            getattr(settings, "CORS_ALLOWED_METHODS", None) or ["*"]
                        ),
                        "allowed_headers": list(
                            getattr(settings, "CORS_ALLOWED_HEADERS", None) or ["*"]
                        ),
                        "expose_headers": list(
                            getattr(settings, "CORS_EXPOSE_HEADERS", None) or []
                        ),
                        "max_age": getattr(settings, "CORS_MAX_AGE", 600),
                    }
                    resolved_middleware.append((cls, cors_kwargs))
                else:
                    resolved_middleware.append(cls)

        # Add Rate Limit middleware if configured.
        if getattr(settings, "RATE_LIMIT_REQUESTS", 0) > 0:
            cls = _resolve_middleware_entry(
                "openviper.middleware.ratelimit.RateLimitMiddleware", critical=True
            )
            if cls is not None:
                resolved_middleware.insert(0, cls)

        app = build_middleware_stack(self._core_app, resolved_middleware)

        # Wrap with the default landing page when no custom root route exists
        has_custom_root = self._has_custom_root_route()
        app = DefaultLandingMiddleware(
            app,
            debug=self.debug,
            version=self.version,
            has_custom_root=has_custom_root,
        )

        # Static and media file serving — DEBUG only.
        # openviper.staticfiles is never imported when DEBUG=False.
        # Additional safety check: never serve in production environment
        env = os.environ.get("ENVIRONMENT", "").lower()
        if self.debug and env not in ("production", "prod"):
            from openviper.staticfiles.handlers import (
                StaticFilesMiddleware,
                _discover_app_static_dirs,
            )

            static_url = getattr(settings, "STATIC_URL", "/static/").rstrip("/")
            static_root = getattr(settings, "STATIC_ROOT", "static")

            # Discover static dirs from all installed apps (includes openviper/admin/static/)
            discovered = [str(d) for d in _discover_app_static_dirs()]
            if static_root not in discovered:
                discovered.append(static_root)

            app = StaticFilesMiddleware(app, url_path=static_url, directories=discovered)  # type: ignore[arg-type]
            logger.debug("StaticFilesMiddleware enabled for %s", static_url)

            media_url = getattr(settings, "MEDIA_URL", "/media/").rstrip("/")
            media_root = getattr(settings, "MEDIA_ROOT", "media")

            app = StaticFilesMiddleware(app, url_path=media_url, directories=[media_root])
            logger.debug("Media serving enabled for %s → %s", media_url, media_root)

        return app

    def _has_custom_root_route(self) -> bool:
        """Check if the user has defined a GET / route (not just OpenAPI routes)."""
        openapi_names = {"openapi_schema", "swagger_ui", "redoc_ui"}
        for route in self.router.routes:
            if getattr(route, "path", "") == "/" and "GET" in getattr(route, "methods", []):
                name = getattr(route, "name", "")
                if name not in openapi_names:
                    return True
        return False

    # ── Core request handler ──────────────────────────────────────────────

    async def _core_app(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        """Resolve route and call the handler (inner ASGI callable)."""
        if scope["type"] == "lifespan":
            await self._handle_lifespan(scope, receive, send)
            return

        if scope["type"] == "http":
            await self._handle_http(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await self._handle_websocket(scope, receive, send)
            return

    async def _handle_http(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        request = Request(scope, receive)
        # Propagate user from middleware, defaults to None if not set
        request.user = scope.get("user")
        request.auth = scope.get("auth")

        token = current_request.set(request)
        try:
            route, path_params = self.router.resolve(request.method, request.path)
            request.path_params = path_params

            # Build handler middleware chain (per-route middlewares)
            handler = route.handler
            for mw in reversed(route.middlewares):
                handler = mw(handler)  # type: ignore[assignment,call-arg]

            response = await self._call_handler(handler, request)
        except Exception as exc:
            response = await self._handle_exception(request, exc)
        finally:
            current_request.reset(token)

        await response(scope, receive, send)

    async def _call_handler(self, handler: Callable[..., Any], request: Request) -> Response:
        """Call a view handler, performing automatic response coercion."""
        handler_id = id(handler)

        # Check if we've pre-computed parameter mapping for this handler
        if handler_id not in self._handler_param_cache:
            sig, hints = _get_handler_signature(handler)
            params = sig.parameters
            param_mapping: dict[str, Any] = {"params": {}, "has_var_keyword": False}

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

            self._handler_param_cache[handler_id] = param_mapping

        param_mapping = self._handler_param_cache[handler_id]
        kwargs: dict[str, Any] = {}

        for name, info in param_mapping["params"].items():
            if info["is_request"] and name not in request.path_params:
                kwargs[name] = request
            elif name in request.path_params:
                kwargs[name] = request.path_params[name]
            elif info["is_var_keyword"]:
                # Populate **kwargs with any path params not already consumed
                for p_name, p_value in request.path_params.items():
                    if p_name not in kwargs:
                        kwargs[p_name] = p_value

        result = handler(**kwargs)
        if inspect.isawaitable(result):
            result = await result

        return self._coerce_response(result)

    def _coerce_response(self, result: Any) -> Response:
        """Convert a handler's return value to a proper Response."""
        if isinstance(result, Response):
            return result

        if isinstance(result, (dict, list)):
            return JSONResponse(result)
        if result is None:
            return Response(b"", status_code=204)
        if isinstance(result, (str, bytes)):
            return PlainTextResponse(result)
        # Try coercing Pydantic models - check for BaseModel explicitly
        try:
            from pydantic import BaseModel

            if isinstance(result, BaseModel):
                return JSONResponse(result.model_dump())
        except ImportError:
            # Pydantic not available, fall through
            pass
        # Fallback: check for model_dump method (duck typing)
        if hasattr(result, "model_dump") and callable(result.model_dump):
            with contextlib.suppress(Exception):
                return JSONResponse(result.model_dump())
        return JSONResponse(result)

    async def _handle_exception(self, request: Request, exc: Exception) -> Response:
        """Dispatch to the appropriate exception handler or return generic error."""
        # Walk the MRO to find the most specific registered handler
        for exc_type in type(exc).__mro__:
            if exc_type in self._exception_handlers:
                handler = self._exception_handlers[exc_type]
                result: Any = handler(request, exc)
                if inspect.isawaitable(result):
                    result = await result
                return self._coerce_response(result)

        if isinstance(exc, HTTPException):
            return self._create_error_response(
                request,
                {"detail": exc.detail},
                status_code=exc.status_code,
                headers=exc.headers,
            )

        logger.exception("Unhandled exception: %s", exc)
        if self.debug:
            return self._create_error_response(
                request,
                {
                    "detail": str(exc),
                    "type": type(exc).__name__,
                    "traceback": traceback.format_exc().splitlines(),
                },
                status_code=500,
            )
        return self._create_error_response(
            request, {"detail": "Internal Server Error"}, status_code=500
        )

    def _create_error_response(
        self,
        request: Request,
        content: dict[str, Any],
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

    async def _handle_websocket(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        """Basic WebSocket handling — reject with 403 if not implemented.

        This prevents resource exhaustion from accepting connections we immediately close.
        """
        # Send websocket.close without accepting to reject the connection
        await send({"type": "websocket.close", "code": 1003, "reason": "Not Implemented"})

    async def _handle_lifespan(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        """ASGI lifespan events: startup and shutdown."""
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                try:
                    # Pre-build the middleware stack during startup so the first
                    # HTTP request is not penalised by the synchronous I/O involved
                    # (app static-dir discovery, settings reads, etc.).
                    await asyncio.to_thread(self._get_middleware_app)

                    # Pre-build OpenAPI schema so the first schema request is instant.
                    if getattr(settings, "OPENAPI_ENABLED", True):
                        self._openapi_schema = await asyncio.to_thread(
                            generate_openapi_schema,
                            routes=self.router.routes,
                            title=self.title,
                            version=self.version,
                        )

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
                    for handler in self._shutdown_handlers:
                        result = handler()
                        if inspect.isawaitable(result):
                            await result
                    await send({"type": "lifespan.shutdown.complete"})
                except Exception as exc:
                    await send({"type": "lifespan.shutdown.failed", "message": str(exc)})
                break  # exit the lifespan event loop

    # ── ASGI callable ─────────────────────────────────────────────────────

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        app = self._get_middleware_app()
        await app(scope, receive, send)

    # ── Dev server shortcut ───────────────────────────────────────────────

    def run(
        self,
        host: str = "127.0.0.1",
        port: int = 8000,
        reload: bool = True,
        log_level: str = "info",
        workers: int = 1,
    ) -> None:
        """Start a uvicorn development server.

        Prefer using ``python viperctl.py runserver`` for project use.

        Args:
            host: Bind address.
            port: Bind port.
            reload: Enable auto-reload on code changes.
            log_level: Uvicorn log level string.
            workers: Number of worker processes (reload must be False).
        """

        uvicorn.run(
            self,
            host=host,
            port=port,
            reload=reload,
            log_level=log_level,
            workers=workers if not reload else 1,
        )

    def test_client(self, **kwargs: Any) -> httpx.AsyncClient:
        """Return an httpx.AsyncClient configured for this app.

        Note: The returned client should be used as an async context manager
        to ensure proper cleanup of resources:

        Example:
            >>> async with app.test_client() as client:
            ...     response = await client.get("/")
        """
        base_url = kwargs.pop("base_url", "http://testserver")
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self),  # type: ignore[arg-type]
            base_url=base_url,
            **kwargs,
        )

    def __repr__(self) -> str:
        return f"OpenViper(title={self.title!r}, routes={len(self.router.routes)})"
