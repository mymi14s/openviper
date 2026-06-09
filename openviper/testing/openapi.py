"""OpenAPI assertion helpers for tests."""

from collections.abc import Mapping


def assert_openapi_path(schema: Mapping[str, object], path: str) -> None:
    paths = schema.get("paths")
    assert isinstance(paths, dict), "OpenAPI schema does not contain a paths object."
    assert path in paths, f"Expected OpenAPI path {path!r} to be present."


def assert_openapi_operation(schema: Mapping[str, object], path: str, method: str) -> None:
    paths = schema.get("paths")
    assert isinstance(paths, dict), "OpenAPI schema does not contain a paths object."
    path_item = paths.get(path)
    assert isinstance(path_item, dict), f"Expected OpenAPI path {path!r} to be present."
    has_op = method.lower() in path_item
    assert has_op, f"Expected {method.upper()} {path} to be present."


def assert_response_schema(
    schema: Mapping[str, object],
    path: str,
    method: str,
    status_code: int,
) -> None:
    operation = get_operation(schema, path, method)
    responses = operation.get("responses")
    assert isinstance(responses, dict), f"{method.upper()} {path} has no responses."
    has_status = str(status_code) in responses
    assert has_status, f"Expected response for {method.upper()} {path} {status_code}."


def assert_request_schema(schema: Mapping[str, object], path: str, method: str) -> None:
    operation = get_operation(schema, path, method)
    assert "requestBody" in operation, f"Expected request schema for {method.upper()} {path}."


def get_operation(schema: Mapping[str, object], path: str, method: str) -> dict[str, object]:
    paths = schema.get("paths")
    assert isinstance(paths, dict), "OpenAPI schema does not contain a paths object."
    path_item = paths.get(path)
    assert isinstance(path_item, dict), f"Expected OpenAPI path {path!r} to be present."
    operation = path_item.get(method.lower())
    assert isinstance(operation, dict), f"Expected {method.upper()} {path} to be present."
    return operation
