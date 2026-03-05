"""Auto-generate OpenAPI 3.1.0 schema from route definitions and type hints."""

from __future__ import annotations

import ast
import inspect
import re
import textwrap
import typing
from typing import TYPE_CHECKING, Any, cast, get_type_hints

if TYPE_CHECKING:
    from openviper.routing.router import Route

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


def _python_type_to_schema(annotation: Any) -> dict[str, Any]:
    """Convert a Python type annotation to a JSON Schema dict."""
    origin = getattr(annotation, "__origin__", None)

    if annotation is inspect.Parameter.empty or annotation is None:
        return {}

    if annotation in _PYTHON_TO_JSON_TYPE:
        return dict(_PYTHON_TO_JSON_TYPE[annotation])

    if origin is list:
        args = getattr(annotation, "__args__", None)
        items_schema = _python_type_to_schema(args[0]) if args else {}
        return {"type": "array", "items": items_schema}

    if origin is dict:
        return {"type": "object"}

    # Optional[X] → X with nullable
    if origin is typing.Union:
        args = annotation.__args__
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            schema = _python_type_to_schema(non_none[0])
            schema["nullable"] = True
            return schema

    # Pydantic model
    if hasattr(annotation, "model_json_schema"):
        return cast("dict[str, Any]", annotation.model_json_schema())

    return {"type": "string"}  # fallback


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
        func._request_schema = serializer_cls
        return func

    return decorator


def _detect_serializer_from_source(handler: Any) -> type | None:
    """Try to detect a Serializer subclass used in the handler body.

    Scans the function source for ``<Name>.validate(`` or
    ``<Name>.model_validate(`` calls and resolves the name against the
    handler's global namespace.
    """
    try:
        source = inspect.getsource(handler)
    except (OSError, TypeError):
        return None

    try:
        source = textwrap.dedent(source)
        tree = ast.parse(source)
    except SyntaxError:
        return None

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
            return cast("type", cls)

    return None


def _resolve_request_schema(handler: Any) -> type | None:
    """Determine the request body schema class for *handler*.

    Resolution order:

    1. ``handler._request_schema`` — set by :func:`request_schema` decorator
    2. ``handler.view_class.serializer_class`` — class-based view attribute
    3. Source-code auto-detection via :func:`_detect_serializer_from_source`
    """
    # 1. Explicit decorator
    schema_cls = getattr(handler, "_request_schema", None)
    if schema_cls is not None:
        return cast("type", schema_cls)

    # 2. Class-based view with serializer_class
    view_cls = getattr(handler, "view_class", None)
    if view_cls is not None:
        schema_cls = getattr(view_cls, "serializer_class", None)
        if schema_cls is not None:
            return cast("type", schema_cls)

        # Scan the view class's mutating methods for serializer usage
        for method_name in ("post", "put", "patch"):
            method = getattr(view_cls, method_name, None)
            if method is not None:
                detected = _detect_serializer_from_source(method)
                if detected is not None:
                    return detected

    # 3. Auto-detect from function body source
    return _detect_serializer_from_source(handler)


def _build_operation(route: Route, method: str) -> dict[str, Any]:
    """Build an OpenAPI operation object for a given route + method."""
    handler = route.handler
    docstring = inspect.getdoc(handler) or ""
    summary = docstring.split("\n")[0] if docstring else route.name or handler.__name__
    description = "\n".join(docstring.split("\n")[1:]).strip() if docstring else ""

    try:
        hints = get_type_hints(handler)
    except Exception:
        hints = {}

    # Path parameters
    parameters = _extract_path_params(route.path)

    # Request body (POST/PUT/PATCH/DELETE)
    request_body: dict[str, Any] | None = None

    if method.upper() in ("POST", "PUT", "PATCH", "DELETE"):
        schema_cls = _resolve_request_schema(handler)
        if schema_cls is not None and hasattr(schema_cls, "model_json_schema"):
            request_body = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": schema_cls.model_json_schema(),
                    }
                },
            }
        else:
            # Fallback: check function parameter annotations for Pydantic models
            sig = inspect.signature(handler)
            for param_name, param in sig.parameters.items():
                annotation = hints.get(param_name, param.annotation)
                if annotation in (inspect.Parameter.empty,):
                    continue
                if hasattr(annotation, "model_json_schema"):
                    request_body = {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": annotation.model_json_schema(),
                            }
                        },
                    }
                    break

            # If still no request body schema found, add a generic object schema
            # (but only for POST/PUT/PATCH, not DELETE which typically uses path params)
            if request_body is None and method.upper() in ("POST", "PUT", "PATCH"):
                request_body = {
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

    # Response schema
    return_type = hints.get("return")
    response_schema: dict[str, Any] = {}
    if return_type and return_type is not type(None):
        response_schema = _python_type_to_schema(return_type)

    responses: dict[str, Any] = {
        "200": {
            "description": "Successful Response",
        }
    }
    if response_schema:
        responses["200"]["content"] = {"application/json": {"schema": response_schema}}
    if method.upper() in ("POST", "PUT", "PATCH", "DELETE"):
        responses["422"] = {"description": "Validation Error"}

    operation: dict[str, Any] = {
        "summary": summary,
        "operationId": f"{method.lower()}_{handler.__name__}",
        "parameters": parameters,
        "responses": responses,
    }
    if description:
        operation["description"] = description
    if request_body:
        operation["requestBody"] = request_body

    # Tags from module
    tag = handler.__module__.split(".")[-1] if hasattr(handler, "__module__") else "default"
    operation["tags"] = [tag]

    return operation


def generate_openapi_schema(
    routes: list[Route],
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

    return {
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
            }
        },
        "security": [{"BearerAuth": []}, {"SessionAuth": []}],
    }
