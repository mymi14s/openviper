"""Auto-generate OpenAPI 3.1.0 schema from route definitions and type hints."""

from __future__ import annotations

import ast
import contextlib
import functools
import hashlib
import html
import inspect
import json
import logging
import re
import textwrap
import typing
import weakref
from typing import TYPE_CHECKING, Any, Protocol, cast, get_type_hints, runtime_checkable

from openviper.openapi.router import read_openapi_settings

if TYPE_CHECKING:
    from collections.abc import Sequence

    from openviper.routing.router import Route


@runtime_checkable
class RouteHandler(Protocol):
    """Structural type for route handler callables with optional metadata.

    Route handlers are async callables that may carry framework-specific
    attributes set by decorators or view machinery.  All optional attributes
    default to ``None`` / ``[]`` so that ``getattr`` calls remain safe.
    """

    __name__: str
    __module__: str

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Invoke the route handler."""
        ...

    # Optional metadata set by decorators or view machinery.
    view_class: type | None
    view_action: str | None
    openapi_request_schema: type | None
    authentication_classes: list[type]
    __globals__: dict[str, Any]


logger = logging.getLogger(__name__)

# JSON Schema equivalents for Python primitives.
PYTHON_TO_JSON_TYPE: dict[type, dict[str, str]] = {
    int: {"type": "integer"},
    float: {"type": "number"},
    str: {"type": "string"},
    bool: {"type": "boolean"},
    bytes: {"type": "string", "format": "binary"},
    list: {"type": "array"},
    dict: {"type": "object"},
}
DOCSTRING_TYPE_TO_SCHEMA: dict[str, dict[str, str]] = {
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "str": {"type": "string"},
    "bool": {"type": "boolean"},
    "bytes": {"type": "string", "format": "binary"},
    "list": {"type": "array"},
    "dict": {"type": "object"},
    "UUID": {"type": "string", "format": "uuid"},
}

# Mutable container so we never need `global` statements.
SCHEMA_CACHE_STORE: list[dict[str, Any] | None] = [None]

# Keyed by weakref to handler; avoids id() reuse bugs after GC.
SERIALIZER_CACHE: weakref.WeakValueDictionary[RouteHandler, type] = weakref.WeakValueDictionary()
# Handlers with no detected serializer (weakref can't hold None).
SERIALIZER_NONE_SET: weakref.WeakSet[RouteHandler] = weakref.WeakSet()
# Type-hints cache keyed by handler reference; entries evicted on GC.
TYPE_HINTS_CACHE: weakref.WeakKeyDictionary[
    RouteHandler,
    dict[str, Any],
] = weakref.WeakKeyDictionary()

# NoneType sentinel for identity checks.
NoneType: type = type(None)

# Segments that are too generic to serve as an OpenAPI tag on their own.
# Path prefixes that trigger deeper route drilling.
GENERIC_PATH_SEGMENTS: frozenset[str] = frozenset({"api", "v1", "v2", "v3"})

# Pattern identifying version segments to exclude from tags.
VERSION_SEGMENT_RE: re.Pattern[str] = re.compile(r"^v\d+$", re.IGNORECASE)


def tag_from_path(path: str) -> str:
    """Derive a meaningful OpenAPI tag from a route path.

    Skips path parameters, generic prefixes such as 'api', and version
    segments such as 'v1' / 'v2'.  Returns the first remaining segment
    capitalised, or 'Root' when none is found.
    """
    parts = [
        p
        for p in path.split("/")
        if p
        and not p.startswith("{")
        and p.lower() not in GENERIC_PATH_SEGMENTS
        and not VERSION_SEGMENT_RE.match(p)
    ]
    return parts[0].capitalize() if parts else "Root"


def reset_openapi_cache() -> None:
    """Clear the generated schema cache. Primarily for tests or dynamic routing."""
    SCHEMA_CACHE_STORE[0] = None
    SERIALIZER_CACHE.clear()
    SERIALIZER_NONE_SET.clear()
    TYPE_HINTS_CACHE.clear()


def filter_openapi_routes(routes: Sequence[Route]) -> list[Route]:
    """Return *routes* with excluded prefixes removed.

    Admin routes under ``/admin`` are excluded unless
    ``OPENAPI["admin_url"]`` is set explicitly.

    Also reads ``OPENAPI["exclude"]``:

    * ``"__ALL__"`` - returns an empty list (router is disabled; this is a
      safety fallback in case filtering is called directly).
    * ``list[str]`` - any route whose path starts with ``/<prefix>`` (case-
      insensitive) for any prefix in the list is dropped.
    * Anything else (empty list, missing setting) - all routes are returned.

    Invalid / unexpected values are treated as an empty exclusion list and a
    warning is logged.
    """
    cfg = read_openapi_settings()
    exclude: str | list[str] = cfg.get("exclude", [])

    if exclude == "__ALL__":
        return []

    if exclude and not isinstance(exclude, list):
        logger.warning(
            "OPENAPI['exclude'] has an unexpected value %r - expected a list or "
            "'__ALL__'. Falling back to no exclusion.",
            exclude,
        )
        exclude = []

    lower_prefixes = [p.lower().strip("/") for p in exclude if isinstance(p, str)]
    if not cfg.get("admin_url"):
        lower_prefixes.append("admin")

    filtered: list[Route] = []
    for route in routes:
        path_lower = route.path.lower().lstrip("/")
        if any(path_lower == p or path_lower.startswith(p + "/") for p in lower_prefixes):
            continue
        filtered.append(route)

    return filtered


@functools.lru_cache(maxsize=256)
def python_type_to_schema(annotation: Any) -> dict[str, Any]:
    """Convert a Python type annotation to a JSON Schema dict."""
    origin = getattr(annotation, "__origin__", None)

    if annotation is inspect.Parameter.empty or annotation is None:
        return {}

    if annotation in PYTHON_TO_JSON_TYPE:
        return PYTHON_TO_JSON_TYPE[annotation].copy()

    if origin is list:
        args = getattr(annotation, "__args__", None)
        return {"type": "array", "items": python_type_to_schema(args[0]) if args else {}}

    if origin is dict:
        return {"type": "object"}
    if origin is typing.Union:
        return union_schema(annotation)

    schema_fn = getattr(annotation, "model_json_schema", None)
    return cast("dict[str, Any]", schema_fn()) if schema_fn else {"type": "string"}


def union_schema(annotation: Any) -> dict[str, Any]:
    """Return the JSON Schema for a Union type (handles Optional[X])."""
    non_none = [a for a in annotation.__args__ if a is not NoneType]
    if len(non_none) == 1:
        # Copy to avoid mutating the cached dict.
        schema = dict(python_type_to_schema(non_none[0]))
        schema["nullable"] = True
        return schema
    return {"type": "string"}  # Multi-type unions lack a single JSON Schema primitive.


def extract_path_params(path: str) -> list[dict[str, Any]]:
    """Extract ``{name:type}`` segments from a path template.

    Parameter names exceeding 128 characters are rejected to prevent
    resource-exhaustion vectors in downstream schema consumers.
    """
    max_param_name_len = 128
    params = []
    for m in re.finditer(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::([a-zA-Z]+))?\}", path):
        name = m.group(1)
        if len(name) > max_param_name_len:
            logger.warning(
                "Path parameter name exceeds %d chars: %r - skipped.",
                max_param_name_len,
                name,
            )
            continue
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
            },
        )
    return params


def openapi_path(path: str) -> str:
    """Convert OpenViper path ``/users/{id:int}`` to OpenAPI ``/users/{id}``."""
    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::[a-zA-Z]+)?\}", r"{\1}", path)


OPENAPI_REQUEST_SCHEMA_ATTR = "openapi_request_schema"


def request_schema(serializer_cls: type) -> typing.Callable[[RouteHandler], RouteHandler]:
    """Attach a serializer class to a route handler for OpenAPI schema generation.

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
    View subclass instead - it is picked up automatically.
    """

    def decorator(func: RouteHandler) -> RouteHandler:
        setattr(func, OPENAPI_REQUEST_SCHEMA_ATTR, serializer_cls)
        return func

    return decorator


def find_validate_call_names(tree: ast.AST) -> list[str]:
    """Extract class names from ``<Name>.validate()`` / ``<Name>.model_validate()`` calls."""
    names: list[str] = []
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
        names.append(func_node.value.id)
    return names


def detect_serializer_from_source(handler: RouteHandler) -> type | None:
    """Try to detect a Serializer subclass used in the handler body.

    Scans the function source for ``<Name>.validate(`` or
    ``<Name>.model_validate(`` calls and resolves the name against the
    handler's global namespace.

    Results are cached by handler reference (weakref-safe).
    """
    if handler in SERIALIZER_NONE_SET:
        return None
    cached = SERIALIZER_CACHE.get(handler)
    if cached is not None:
        return cast("type", cached)

    try:
        source = inspect.getsource(handler)
    except OSError, TypeError:
        SERIALIZER_NONE_SET.add(handler)
        return None

    try:
        source = textwrap.dedent(source)
        tree = ast.parse(source)
    except SyntaxError:
        SERIALIZER_NONE_SET.add(handler)
        return None

    # Globals are the only reliable namespace for bare name resolution.
    handler_globals = getattr(handler, "__globals__", {})
    result = None
    for cls_name in find_validate_call_names(tree):
        cls = handler_globals.get(cls_name)
        if cls is not None and hasattr(cls, "model_json_schema"):
            result = cast("type", cls)
            break

    if result is None:
        SERIALIZER_NONE_SET.add(handler)
    else:
        with contextlib.suppress(TypeError):
            SERIALIZER_CACHE[handler] = result
    return result


def detect_serializer_from_docstring(handler: RouteHandler) -> type | None:
    """Try to detect a Serializer subclass from the handler's docstring.

    Scans for tags like ``Request: <Name>`` or ``Body: <Name>`` and
    resolves the name against the handler's globals.
    """
    doc = inspect.getdoc(handler)
    if not doc:
        return None

    # Docstring tags are a lightweight alternative to explicit decorators.
    m = re.search(r"(?:Request|Body):\s*([a-zA-Z_][a-zA-Z0-9_]*)", doc)
    if not m:
        return None

    cls_name = m.group(1)
    # Globals are the only reliable namespace for bare name resolution.
    handler_globals = getattr(handler, "__globals__", {})
    cls = handler_globals.get(cls_name)
    if cls is not None and hasattr(cls, "model_json_schema"):
        return cast("type", cls)
    return None


def extract_json_from_docstring(doc: str | None, header: str) -> dict[str, Any] | None:
    """Extract and parse a JSON block following a specific header in the docstring.

    Example:
        Example Request:
        {
            "foo": "bar"
        }

    """
    if not doc:
        return None

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


def extract_inline_request_schema(doc: str | None) -> dict[str, Any] | None:
    """Extract a lightweight request schema from an inline docstring body."""
    if not doc:
        return None

    match = re.search(r"(?:Request|Body):\s*\{(?P<body>.*?)\}", doc, re.DOTALL)
    if match is None:
        return None

    properties: dict[str, dict[str, Any]] = {}
    required: list[str] = []
    for line in match.group("body").splitlines():
        field_match = re.search(
            r'["\'](?P<name>[a-zA-Z_][a-zA-Z0-9_]*)["\']\s*:\s*(?P<type>[a-zA-Z_][a-zA-Z0-9_]*)',
            line,
        )
        if field_match is None:
            continue

        field_name = field_match.group("name")
        field_type = field_match.group("type")
        property_schema: dict[str, Any] = DOCSTRING_TYPE_TO_SCHEMA.get(
            field_type,
            {"type": "string"},
        ).copy()

        suffix = line[field_match.end() :]
        if field_type == "UUID" or "UUID" in suffix:
            property_schema["format"] = "uuid"

        choices = re.findall(r'["\']([^"\']+)["\']', suffix)
        if choices:
            property_schema["enum"] = choices

        properties[field_name] = property_schema
        required.append(field_name)

    if not properties:
        return None

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "title": "Request Body",
    }


def operation_doc_handler(handler: RouteHandler, method: str) -> RouteHandler:
    """Return the best handler source for method-level OpenAPI documentation."""
    if getattr(handler, "view_action", None):
        return handler

    view_cls = getattr(handler, "view_class", None)
    if view_cls is None:
        return handler

    return getattr(view_cls, method.lower(), handler)


def flush_paragraph(paragraph: list[str], rendered: list[str]) -> None:
    """Append the accumulated paragraph lines as an HTML <p> element."""
    if paragraph:
        rendered.append(f"<p>{html.escape(' '.join(paragraph))}</p>")
        paragraph.clear()


def collect_brace_block(
    lines: list[str],
    start_index: int,
    first_line: str,
) -> tuple[list[str], int]:
    """Gather lines until braces balance, returning (block_lines, next_index)."""
    block_lines = [first_line.strip()] if first_line.strip() else []
    brace_depth = first_line.count("{") - first_line.count("}")
    index = start_index
    while index < len(lines) and brace_depth > 0:
        block_line = lines[index].strip()
        block_lines.append(block_line)
        brace_depth += block_line.count("{") - block_line.count("}")
        index += 1
    return block_lines, index


def format_operation_description(docstring: str) -> str:
    """Render structured docstrings as safe HTML for documentation UIs."""
    if not docstring:
        return ""

    body = "\n".join(docstring.split("\n")[1:]).strip()
    if not body:
        return ""

    lines = body.splitlines()
    rendered: list[str] = []
    paragraph: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            flush_paragraph(paragraph, rendered)
            index += 1
            continue

        if stripped.startswith(("Request:", "Body:")) and "{" not in stripped:
            flush_paragraph(paragraph, rendered)
            label, value = stripped.split(":", maxsplit=1)
            rendered.append(
                f"<p><strong>{html.escape(label)}:</strong> {html.escape(value.strip())}</p>",
            )
            index += 1
            continue

        if stripped.startswith(("Body:", "Request:")) and "{" in stripped:
            flush_paragraph(paragraph, rendered)
            label, remainder = stripped.split(":", maxsplit=1)
            block_lines, index = collect_brace_block(lines, index + 1, remainder)
            rendered.append(
                f"<p><strong>{html.escape(label)}:</strong></p>"
                f"<pre><code>{html.escape(chr(10).join(block_lines))}</code></pre>",
            )
            continue

        if stripped.startswith(("Example Request:", "Example Response:")):
            flush_paragraph(paragraph, rendered)
            label, remainder = stripped.split(":", maxsplit=1)
            block_lines, index = collect_brace_block(lines, index + 1, remainder)
            rendered.append(
                f"<p><strong>{html.escape(label)}:</strong></p>"
                f"<pre><code>{html.escape(chr(10).join(block_lines))}</code></pre>",
            )
            continue

        paragraph.append(stripped)
        index += 1

    if paragraph:
        rendered.append(f"<p>{html.escape(' '.join(paragraph))}</p>")

    return "".join(rendered)


def detect_serializer_from_method(method: object) -> type | None:
    """Try docstring then source detection on a single method object."""
    detected = detect_serializer_from_docstring(method)
    if detected is not None:
        return detected
    return detect_serializer_from_source(method)


def resolve_view_class_schema(view_cls: type, handler: RouteHandler) -> type | None:
    """Resolve a serializer from a class-based view's attributes and methods."""
    schema_cls = getattr(view_cls, "serializer_class", None)
    if schema_cls is not None:
        return cast("type", schema_cls)

    view_action = getattr(handler, "view_action", None)
    if view_action:
        method = getattr(view_cls, view_action, None)
        if method is not None:
            detected = detect_serializer_from_method(method)
            if detected is not None:
                return detected

    for method_name in ("post", "put", "patch"):
        method = getattr(view_cls, method_name, None)
        if method is not None:
            detected = detect_serializer_from_method(method)
            if detected is not None:
                return detected

    return None


def resolve_request_schema(handler: RouteHandler) -> type | None:
    """Determine the request body schema class for *handler*.

    Resolution order:

    1. ``handler.openapi_request_schema`` - set by :func:`request_schema` decorator
    2. ``handler.view_class.serializer_class`` - class-based view attribute
    3. Source-code auto-detection via :func:`detect_serializer_from_source`
    """
    # The decorator is the most explicit signal; it overrides all heuristics.
    schema_cls = getattr(handler, OPENAPI_REQUEST_SCHEMA_ATTR, None)
    if schema_cls is not None:
        return cast("type", schema_cls)

    view_cls = getattr(handler, "view_class", None)
    if view_cls is not None:
        detected = resolve_view_class_schema(view_cls, handler)
        if detected is not None:
            return detected

    # Docstring tags are a lightweight alternative to decorators.
    detected = detect_serializer_from_method(handler)
    if detected is not None:
        return detected

    return detect_serializer_from_source(handler)


def find_pydantic_param_schema(
    handler: RouteHandler,
    hints: dict[str, Any],
) -> dict[str, Any] | None:
    """Return a request body dict if any handler parameter is a Pydantic model."""
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
    return None


MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH"})
BODY_REQUIRED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def build_request_body(
    handler: RouteHandler,
    method: str,
    hints: dict[str, Any],
    doc_handler: RouteHandler | None = None,
) -> dict[str, Any] | None:
    """Resolve request body schema for *handler* at *method*."""
    schema_cls = resolve_request_schema(handler)
    content: dict[str, Any] = {}
    if schema_cls is not None and hasattr(schema_cls, "model_json_schema"):
        content["application/json"] = {"schema": schema_cls.model_json_schema()}

    doc = inspect.getdoc(doc_handler or handler)
    example = extract_json_from_docstring(doc, "Example Request")
    if example:
        if "application/json" not in content:
            content["application/json"] = {"schema": {"type": "object", "title": "Request Body"}}
        content["application/json"]["example"] = example

    if "application/json" not in content:
        inline_schema = extract_inline_request_schema(doc)
        if inline_schema is not None:
            content["application/json"] = {"schema": inline_schema}

    if content:
        return {"required": True, "content": content}

    param_body = find_pydantic_param_schema(handler, hints)
    if param_body is not None:
        return param_body

    # Default schema prevents hidden body fields in Swagger UI.
    if method.upper() in MUTATING_METHODS:
        return {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "title": "Request Body",
                        "description": "JSON request body",
                    },
                },
            },
        }
    return None


def build_responses(
    method: str,
    docstring: str,
    response_schema: dict[str, Any],
) -> dict[str, Any]:
    """Build the ``responses`` dict for an OpenAPI operation."""
    responses: dict[str, Any] = {"200": {"description": "Successful Response"}}
    if response_schema:
        responses["200"]["content"] = {"application/json": {"schema": response_schema}}

    # Example responses in docstrings aid client-generation tooling.
    resp_example = extract_json_from_docstring(docstring, "Example Response")
    if resp_example:
        if "content" not in responses["200"]:
            responses["200"]["content"] = {"application/json": {}}
        responses["200"]["content"]["application/json"]["example"] = resp_example
    if method.upper() in BODY_REQUIRED_METHODS:
        responses["422"] = {"description": "Validation Error"}
    return responses


def build_operation(route: Route, method: str) -> dict[str, Any]:
    """Build an OpenAPI operation object for a given route + method."""
    handler = route.handler
    doc_handler = operation_doc_handler(handler, method)
    docstring = inspect.getdoc(doc_handler) or ""
    summary = docstring.split("\n")[0] if docstring else route.name or handler.__name__
    description = format_operation_description(docstring)

    # Reuse cached hints to avoid repeated introspection overhead.
    if doc_handler not in TYPE_HINTS_CACHE:
        try:
            hints: dict[str, Any] = get_type_hints(doc_handler)
        except NameError, AttributeError, TypeError:
            hints = {}
        TYPE_HINTS_CACHE[doc_handler] = hints
    hints = TYPE_HINTS_CACHE[doc_handler]

    # Path params come from the route template, not from handler signatures.
    parameters = extract_path_params(route.path)

    # HTTP semantics require a body for state-mutating methods.
    request_body: dict[str, Any] | None = None
    if method.upper() in BODY_REQUIRED_METHODS:
        request_body = build_request_body(handler, method, hints, doc_handler)

    # The return annotation drives the response schema when present.
    return_type = hints.get("return")
    response_schema: dict[str, Any] = {}
    if return_type is not None and return_type is not NoneType:
        response_schema = python_type_to_schema(return_type)

    responses = build_responses(method, docstring, response_schema)

    # Explicit tags override path-derived heuristics.
    tag = route.tags[0] if route.tags else tag_from_path(route.path)

    # Module suffix disambiguates same-named handlers.
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

    per_route_security = build_per_route_security(handler)
    if per_route_security is not None:
        operation["security"] = per_route_security

    return operation


def build_per_route_security(handler: RouteHandler) -> list[dict[str, list[Any]]] | None:
    """Return an explicit ``security`` list for *handler* when it restricts auth.

    Returns ``None`` when no per-route ``authentication_classes`` are set, which
    lets the global security requirement inherited from ``generate_openapi_schema``
    remain in effect.  Returns a non-empty list when the handler or its
    associated view class declares specific authentication classes.
    """
    view_cls = getattr(handler, "view_class", None)
    if view_cls is not None:
        auth_classes: list[type] = getattr(view_cls, "authentication_classes", [])
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

    return security or None


def generate_openapi_schema(
    routes: Sequence[Route],
    title: str = "OpenViper API",
    description: str = "",
    version: str = "1.0.0",
) -> dict[str, Any]:
    """Build a complete OpenAPI 3.1.0 document from the router's routes.

    Args:
        routes: All registered Route objects.
        title: API title.
        description: API description.
        version: API version string included in the ``info`` block.

    Returns:
        OpenAPI 3.1.0 document as a dict.

    """
    # Route path fingerprint prevents stale schema cache hits.
    # Per-component hashing prevents delimiter-injection collisions.
    routes_fingerprint = ",".join(sorted(f"{r.path}:{','.join(sorted(r.methods))}" for r in routes))
    raw_key = (
        hashlib.sha256(title.encode()).hexdigest()
        + hashlib.sha256(description.encode()).hexdigest()
        + hashlib.sha256(version.encode()).hexdigest()
        + hashlib.sha256(routes_fingerprint.encode()).hexdigest()
    )
    cache_key = hashlib.sha256(raw_key.encode()).hexdigest()

    cached_entry: dict[str, Any] | None = SCHEMA_CACHE_STORE[0]
    if cached_entry is not None and cached_entry.get("_cache_key") == cache_key:
        return cast("dict[str, Any]", cached_entry.get("schema"))

    paths: dict[str, dict[str, Any]] = {}

    # Self-referential docs endpoints would pollute the schema.
    internal_paths = {"/open-api/openapi.json", "/open-api/docs", "/open-api/redoc"}

    for route in routes:
        normalised_path = openapi_path(route.path)
        if normalised_path in internal_paths:
            continue

        if normalised_path not in paths:
            paths[normalised_path] = {}

        for method in sorted(route.methods):
            if method in {"HEAD", "OPTIONS"}:
                continue  # HEAD/OPTIONS are transport-level; they add noise to business docs.
            paths[normalised_path][method.lower()] = build_operation(route, method)

    schema: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {
            "title": title,
            "description": description,
            "version": version,
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
                        "Token authentication. Supply the header as: Authorization: Token <token>"
                    ),
                },
            },
        },
        "security": [{"BearerAuth": []}, {"SessionAuth": []}, {"TokenAuth": []}],
    }

    SCHEMA_CACHE_STORE[0] = {"_cache_key": cache_key, "schema": schema}
    return schema
