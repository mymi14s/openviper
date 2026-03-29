"""Auto-generate OpenAPI 3.1.0 schema from route definitions and type hints."""

from __future__ import annotations

import ast
import contextlib
import functools
import hashlib
import inspect
import json
import logging
import re
import textwrap
import typing
import weakref
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, cast, get_type_hints

from openviper.conf import settings

if TYPE_CHECKING:
    from openviper.routing.router import Route

logger = logging.getLogger(__name__)

# Map Python types to JSON Schema types
_PYTHON_TO_JSON_TYPE: dict[type, dict[str, str]] = {
    int: {"type": "integer"},
    float: {"type": "number"},
    str: {"type": "string"},
    bool: {"type": "boolean"},
    bytes: {"type": "string", "format": "binary"},
    list: {"type": "array"},
    dict: {"type": "object"},
}

# Mutable container so we never need `global` statements.
# _SCHEMA_CACHE_STORE[0] is either None or {"_cache_key": str, "schema": dict}.
_SCHEMA_CACHE_STORE: list[dict[str, Any] | None] = [None]

# Keyed by weakref to handler; avoids id() reuse bugs after GC.
_SERIALIZER_CACHE: weakref.WeakValueDictionary[Any, Any] = weakref.WeakValueDictionary()
# Tracks handlers whose detected serializer is None (weakref can't store None).
_SERIALIZER_NONE_IDS: set[int] = set()
_TYPE_HINTS_CACHE: dict[int, dict[str, Any]] = {}

# NoneType sentinel for isinstance/identity checks (avoids unidiomatic type() calls).
NoneType: type = type(None)


def reset_openapi_cache() -> None:
    """Clear the generated schema cache. Primarily for tests or dynamic routing."""
    _SCHEMA_CACHE_STORE[0] = None
    _SERIALIZER_CACHE.clear()
    _SERIALIZER_NONE_IDS.clear()
    _TYPE_HINTS_CACHE.clear()


def filter_openapi_routes(routes: Sequence[Route]) -> list[Route]:
    """Return *routes* with excluded prefixes removed.

    Reads ``settings.OPENAPI_EXCLUDE``:

    * ``"__ALL__"`` — returns an empty list (router is disabled; this is a
      safety fallback in case filtering is called directly).
    * ``list[str]`` — any route whose path starts with ``/<prefix>`` (case-
      insensitive) for any prefix in the list is dropped.
    * Anything else (empty list, missing setting) — all routes are returned.

    Invalid / unexpected values are treated as an empty exclusion list and a
    warning is logged.
    """

    exclude: Any = getattr(settings, "OPENAPI_EXCLUDE", [])

    if exclude == "__ALL__":
        return []

    if not exclude:
        return list(routes)

    if not isinstance(exclude, list):
        logger.warning(
            "OPENAPI_EXCLUDE has an unexpected value %r — expected a list or "
            "'__ALL__'. Falling back to no exclusion.",
            exclude,
        )
        return list(routes)

    lower_prefixes = [p.lower().strip("/") for p in exclude if isinstance(p, str)]

    filtered: list[Route] = []
    for route in routes:
        path_lower = route.path.lower().lstrip("/")
        if any(path_lower == p or path_lower.startswith(p + "/") for p in lower_prefixes):
            continue
        filtered.append(route)

    return filtered


@functools.lru_cache(maxsize=256)
def _python_type_to_schema(annotation: Any) -> dict[str, Any]:
    """Convert a Python type annotation to a JSON Schema dict."""
    origin = getattr(annotation, "__origin__", None)

    if annotation is inspect.Parameter.empty or annotation is None:
        return {}

    if annotation in _PYTHON_TO_JSON_TYPE:
        return _PYTHON_TO_JSON_TYPE[annotation].copy()

    if origin is list:
        args = getattr(annotation, "__args__", None)
        items_schema = _python_type_to_schema(args[0]) if args else {}
        return {"type": "array", "items": items_schema}

    if origin is dict:
        return {"type": "object"}

    # Optional[X] → X with nullable; delegate to helper to keep return count ≤ 6
    if origin is typing.Union:
        return _union_schema(annotation)

    # Pydantic model
    if hasattr(annotation, "model_json_schema"):
        return cast("dict[str, Any]", annotation.model_json_schema())

    return {"type": "string"}  # fallback


def _union_schema(annotation: Any) -> dict[str, Any]:
    """Return the JSON Schema for a Union type (handles Optional[X])."""
    non_none = [a for a in annotation.__args__ if a is not NoneType]
    if len(non_none) == 1:
        # copy to avoid mutating the lru_cache-held dict for the inner type
        schema = dict(_python_type_to_schema(non_none[0]))
        schema["nullable"] = True
        return schema
    return {"type": "string"}  # multi-type union fallback


def _extract_path_params(path: str) -> list[dict[str, Any]]:
    """Extract ``{name:type}`` segments from a path template."""
    params = []
    for m in re.finditer(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::([a-zA-Z]+))?\}", path):
        name = m.group(1)
        conv = m.group(2) or "str"
        type_schema: dict[str, Any] = {
            "str": {"type": "string"},
            "int": {"type": "integer"},
            "float": {"type": "number"},
            "uuid": {"type": "string", "format": "uuid"},
            "path": {"type": "string"},
            "slug": {"type": "string"},
        }.get(conv, {"type": "string"})
        params.append(
            {
                "name": name,
                "in": "path",
                "required": True,
                "schema": type_schema,
            }
        )
    return params


def _openapi_path(path: str) -> str:
    """Convert OpenViper path ``/users/{id:int}`` to OpenAPI ``/users/{id}``."""
    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::[a-zA-Z]+)?\}", r"{\1}", path)


# ── Request schema declaration ────────────────────────────────────────────────

# Public attribute name used to carry the schema class on a handler function.
OPENAPI_REQUEST_SCHEMA_ATTR = "openapi_request_schema"


def request_schema(serializer_cls: type) -> Any:
    """Decorator that attaches a serializer class to a route handler.

    The OpenAPI schema generator will use it to produce a ``requestBody``
    entry so that Swagger UI displays the input form correctly.

    Works with both function-based and class-based views.

    Example::

        from openviper.openapi.schema import request_schema

        @router.post("/blogs")
        @request_schema(BlogSerializer)
        async def create_blog(request):
            ...

    For class-based views, prefer setting ``serializer_class`` on the
    View subclass instead — it is picked up automatically.
    """

    def decorator(func: Any) -> Any:
        setattr(func, OPENAPI_REQUEST_SCHEMA_ATTR, serializer_cls)
        return func

    return decorator


def _detect_serializer_from_source(handler: Any) -> type | None:
    """Try to detect a Serializer subclass used in the handler body.

    Scans the function source for ``<Name>.validate(`` or
    ``<Name>.model_validate(`` calls and resolves the name against the
    handler's global namespace.

    Results are cached by handler object identity (weakref-safe).
    """
    handler_id = id(handler)
    if handler_id in _SERIALIZER_NONE_IDS:
        return None
    cached = _SERIALIZER_CACHE.get(handler)
    if cached is not None:
        return cast("type", cached)

    try:
        source = inspect.getsource(handler)
    except OSError, TypeError:
        _SERIALIZER_NONE_IDS.add(handler_id)
        return None

    try:
        source = textwrap.dedent(source)
        tree = ast.parse(source)
    except SyntaxError:
        _SERIALIZER_NONE_IDS.add(handler_id)
        return None

    result = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_node = node.func
        if not isinstance(func_node, ast.Attribute):
            continue
        if func_node.attr not in ("validate", "model_validate"):
            continue
        if not isinstance(func_node.value, ast.Name):
            continue
        cls_name = func_node.value.id

        # Resolve the name in the handler's module globals
        handler_globals = getattr(handler, "__globals__", {})
        cls = handler_globals.get(cls_name)
        if cls is not None and hasattr(cls, "model_json_schema"):
            result = cast("type", cls)
            break

    if result is None:
        _SERIALIZER_NONE_IDS.add(handler_id)
    else:
        with contextlib.suppress(TypeError):
            _SERIALIZER_CACHE[handler] = result
    return result


def _detect_serializer_from_docstring(handler: Any) -> type | None:
    """Try to detect a Serializer subclass from the handler's docstring.

    Scans for tags like ``Request: <Name>`` or ``Body: <Name>`` and
    resolves the name against the handler's globals.
    """
    doc = inspect.getdoc(handler)
    if not doc:
        return None

    # Match "Request: SerializerName" or "Body: SerializerName"
    m = re.search(r"(?:Request|Body):\s*([a-zA-Z_][a-zA-Z0-9_]*)", doc)
    if not m:
        return None

    cls_name = m.group(1)
    # Resolve the name in the handler's module globals
    handler_globals = getattr(handler, "__globals__", {})
    cls = handler_globals.get(cls_name)
    if cls is not None and hasattr(cls, "model_json_schema"):
        return cast("type", cls)
    return None


def _extract_json_from_docstring(doc: str | None, header: str) -> dict[str, Any] | None:
    """Extract and parse a JSON block following a specific header in the docstring.

    Example:
        Example Request:
        {
            "foo": "bar"
        }
    """
    if not doc:
        return None

    # Locate the header then use raw_decode to parse the JSON block that follows.
    # raw_decode stops at the correct closing brace without any regex backtracking,
    # making this safe against crafted/malformed docstrings.
    header_marker = f"{header}:"
    idx = doc.find(header_marker)
    if idx == -1:
        return None

    brace_idx = doc.find("{", idx + len(header_marker))
    if brace_idx == -1:
        return None

    try:
        obj, _ = json.JSONDecoder().raw_decode(doc, brace_idx)
    except json.JSONDecodeError, ValueError:
        return None

    if not isinstance(obj, dict):
        return None
    return cast("dict[str, Any]", obj)


def _resolve_request_schema(handler: Any) -> type | None:
    """Determine the request body schema class for *handler*.

    Resolution order:

    1. ``handler.openapi_request_schema`` — set by :func:`request_schema` decorator
    2. ``handler.view_class.serializer_class`` — class-based view attribute
    3. Source-code auto-detection via :func:`_detect_serializer_from_source`
    """
    # 1. Explicit decorator
    schema_cls = getattr(handler, OPENAPI_REQUEST_SCHEMA_ATTR, None)
    if schema_cls is not None:
        return cast("type", schema_cls)

    # 2. Class-based view with serializer_class
    view_cls = getattr(handler, "view_class", None)
    if view_cls is not None:
        schema_cls = getattr(view_cls, "serializer_class", None)
        if schema_cls is not None:
            return cast("type", schema_cls)

        # Scan the view class's mutating methods for serializer usage
        view_action = getattr(handler, "view_action", None)
        if view_action:
            method = getattr(view_cls, view_action, None)
            if method is not None:
                detected = _detect_serializer_from_docstring(method)
                if detected is not None:
                    return detected
                detected = _detect_serializer_from_source(method)
                if detected is not None:
                    return detected

        for method_name in ("post", "put", "patch"):
            method = getattr(view_cls, method_name, None)
            if method is not None:
                detected = _detect_serializer_from_docstring(method)
                if detected is not None:
                    return detected
                detected = _detect_serializer_from_source(method)
                if detected is not None:
                    return detected

    # 3. Docstring detection (Request: MySerializer)
    detected = _detect_serializer_from_docstring(handler)
    if detected is not None:
        return detected

    # 4. Auto-detect from function body source
    return _detect_serializer_from_source(handler)


def _build_request_body(handler: Any, method: str, hints: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve request body schema for *handler* at *method*."""
    schema_cls = _resolve_request_schema(handler)
    content: dict[str, Any] = {}
    if schema_cls is not None and hasattr(schema_cls, "model_json_schema"):
        content["application/json"] = {"schema": schema_cls.model_json_schema()}

    # Extract example from docstring if present
    doc = inspect.getdoc(handler)
    example = _extract_json_from_docstring(doc, "Example Request")
    if example:
        if "application/json" not in content:
            content["application/json"] = {"schema": {"type": "object", "title": "Request Body"}}
        content["application/json"]["example"] = example

    if content:
        return {"required": True, "content": content}

    # Fallback: check function parameter annotations for Pydantic models
    sig = inspect.signature(handler)
    for param_name, param in sig.parameters.items():
        annotation = hints.get(param_name, param.annotation)
        if annotation is inspect.Parameter.empty:
            continue
        if hasattr(annotation, "model_json_schema"):
            return {
                "required": True,
                "content": {"application/json": {"schema": annotation.model_json_schema()}},
            }

    # Generic fallback for POST/PUT/PATCH (not DELETE which uses path params)
    if method.upper() in ("POST", "PUT", "PATCH"):
        return {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "title": "Request Body",
                        "description": "JSON request body",
                    }
                }
            },
        }
    return None


def _build_operation(route: Route, method: str) -> dict[str, Any]:
    """Build an OpenAPI operation object for a given route + method."""
    handler = route.handler
    handler_id = id(handler)
    docstring = inspect.getdoc(handler) or ""
    summary = docstring.split("\n")[0] if docstring else route.name or handler.__name__
    description = "\n".join(docstring.split("\n")[1:]).strip() if docstring else ""

    # Use cached type hints if available
    if handler_id not in _TYPE_HINTS_CACHE:
        try:
            hints: dict[str, Any] = get_type_hints(handler)
        except NameError, AttributeError, TypeError:
            hints = {}
        _TYPE_HINTS_CACHE[handler_id] = hints
    hints = _TYPE_HINTS_CACHE[handler_id]

    # Path parameters
    parameters = _extract_path_params(route.path)

    # Request body (POST/PUT/PATCH/DELETE)
    request_body: dict[str, Any] | None = None
    if method.upper() in ("POST", "PUT", "PATCH", "DELETE"):
        request_body = _build_request_body(handler, method, hints)

    # Response schema
    return_type = hints.get("return")
    response_schema: dict[str, Any] = {}
    if return_type is not None and return_type is not NoneType:
        response_schema = _python_type_to_schema(return_type)

    responses: dict[str, Any] = {"200": {"description": "Successful Response"}}
    if response_schema:
        responses["200"]["content"] = {"application/json": {"schema": response_schema}}

    # Extract response example from docstring if present
    resp_example = _extract_json_from_docstring(docstring, "Example Response")
    if resp_example:
        if "content" not in responses["200"]:
            responses["200"]["content"] = {"application/json": {}}
        responses["200"]["content"]["application/json"]["example"] = resp_example
    if method.upper() in ("POST", "PUT", "PATCH", "DELETE"):
        responses["422"] = {"description": "Validation Error"}

    # Tags: use the first non-param path segment so /{id}/foo → "Foo" not "{id}"
    path_parts = [p for p in route.path.split("/") if p and not p.startswith("{")]
    tag = path_parts[0].capitalize() if path_parts else "Root"

    # operationId: include module suffix to avoid collisions between same-named handlers
    module = getattr(handler, "__module__", "") or ""
    module_suffix = module.split(".")[-1] if module else ""
    op_id = (
        f"{method.lower()}_{module_suffix}_{handler.__name__}"
        if module_suffix
        else f"{method.lower()}_{handler.__name__}"
    )

    operation: dict[str, Any] = {
        "summary": summary,
        "operationId": op_id,
        "parameters": parameters,
        "responses": responses,
        "tags": [tag],
    }
    if description:
        operation["description"] = description
    if request_body:
        operation["requestBody"] = request_body

    per_route_security = _build_per_route_security(handler)
    if per_route_security is not None:
        operation["security"] = per_route_security

    return operation


def _build_per_route_security(handler: Any) -> list[dict[str, list[Any]]] | None:
    """Return an explicit ``security`` list for *handler* when it restricts auth.

    Returns ``None`` when no per-route ``authentication_classes`` are set, which
    lets the global security requirement inherited from ``generate_openapi_schema``
    remain in effect.  Returns a non-empty list when the handler or its
    associated view class declares specific authentication classes.
    """
    view_cls = getattr(handler, "view_class", None)
    if view_cls is not None:
        auth_classes: list[Any] = getattr(view_cls, "authentication_classes", [])
    else:
        auth_classes = getattr(handler, "authentication_classes", [])

    if not auth_classes:
        return None

    security: list[dict[str, list[Any]]] = []
    scheme_map: dict[str, str] = {
        "TokenAuthentication": "TokenAuth",
        "JWTAuthentication": "BearerAuth",
        "SessionAuthentication": "SessionAuth",
    }
    for cls in auth_classes:
        name = getattr(cls, "__name__", "")
        scheme = scheme_map.get(name)
        if scheme:
            security.append({scheme: []})

    return security if security else None


def generate_openapi_schema(
    routes: Sequence[Route],
    title: str = "OpenViper API",
    version: str = "0.0.1",
    description: str = "",
) -> dict[str, Any]:
    """Build a complete OpenAPI 3.1.0 document from the router's routes.

    Args:
        routes: All registered Route objects.
        title: API title.
        version: API version string.
        description: API description.

    Returns:
        OpenAPI 3.1.0 document as a dict.
    """
    # Include a fingerprint of the route paths so that filtered and unfiltered
    # route sets produce different cache keys, preventing stale schema hits after
    # OPENAPI_EXCLUDE changes without a full process restart.
    routes_fingerprint = ",".join(sorted(f"{r.path}:{','.join(sorted(r.methods))}" for r in routes))
    raw_key = f"{title}\x00{version}\x00{description}\x00{routes_fingerprint}"
    cache_key = hashlib.sha256(raw_key.encode()).hexdigest()

    cached_entry: dict[str, Any] | None = _SCHEMA_CACHE_STORE[0]
    if cached_entry is not None and cached_entry.get("_cache_key") == cache_key:
        return cast("dict[str, Any]", cached_entry.get("schema"))

    paths: dict[str, dict[str, Any]] = {}

    # Skip internal OpenAPI routes
    internal_paths = {"/open-api/openapi.json", "/open-api/docs", "/open-api/redoc"}

    for route in routes:
        openapi_path = _openapi_path(route.path)
        if openapi_path in internal_paths:
            continue

        if openapi_path not in paths:
            paths[openapi_path] = {}

        for method in sorted(route.methods):
            if method == "HEAD":
                continue  # Omit HEAD; it mirrors GET
            paths[openapi_path][method.lower()] = _build_operation(route, method)

    schema: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {
            "title": title,
            "version": version,
            "description": description,
        },
        "paths": paths,
        "components": {
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                },
                "SessionAuth": {
                    "type": "apiKey",
                    "in": "cookie",
                    "name": "sessionid",
                },
                "TokenAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "Authorization",
                    "description": (
                        "Token authentication. "
                        "Supply the header as: Authorization: Token <token>"
                    ),
                },
            }
        },
        "security": [{"BearerAuth": []}, {"SessionAuth": []}, {"TokenAuth": []}],
    }

    _SCHEMA_CACHE_STORE[0] = {"_cache_key": cache_key, "schema": schema}
    return schema
