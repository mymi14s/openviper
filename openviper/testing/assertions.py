"""Readable assertion helpers for OpenViper tests."""

import json
import typing as t
from collections.abc import Mapping, Sequence

if t.TYPE_CHECKING:
    import httpx


def assert_status(response: httpx.Response, expected: int) -> None:
    actual = response.status_code
    assert actual == expected, f"Expected status {expected}, got {actual}: {response.text}"


def assert_header(response: httpx.Response, name: str, expected: str | None = None) -> None:
    actual = response.headers.get(name)
    assert actual is not None, f"Expected response header {name!r} to be present."
    if expected is not None:
        assert actual == expected, f"Expected header {name!r}={expected!r}, got {actual!r}."


def assert_cookie(response: httpx.Response, name: str) -> None:
    assert name in response.cookies, f"Expected response cookie {name!r} to be present."


def assert_response_json(response: httpx.Response, expected: object) -> None:
    actual = response.json()
    assert actual == expected, format_json_difference(actual, expected)


def assert_json_contains(response: httpx.Response, expected: Mapping[str, object]) -> None:
    payload = response.json()
    assert isinstance(payload, dict), "Expected response JSON to be an object."
    missing = {
        key: value for key, value in expected.items() if key not in payload or payload[key] != value
    }
    assert not missing, "JSON response did not contain expected values: " + json.dumps(missing)


def assert_redirects(response: httpx.Response, expected_location: str | None = None) -> None:
    assert response.status_code in {
        301,
        302,
        303,
        307,
        308,
    }, f"Expected redirect status, got {response.status_code}."
    if expected_location is not None:
        actual = response.headers.get("location")
        assert (
            actual == expected_location
        ), f"Expected redirect to {expected_location!r}, got {actual!r}."


def assert_json_path(payload: Mapping[str, object], path: str, expected: object) -> None:
    current: object = payload
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        raise AssertionError(f"JSON path {path!r} was missing at {part!r}.")
    assert current == expected, f"Expected JSON path {path!r}={expected!r}, got {current!r}."


def assert_validation_error(response: httpx.Response, field: str) -> None:
    payload = response.json()
    assert contains_validation_field(
        payload, field
    ), f"Expected validation error for field {field!r}, got {payload!r}."


def assert_field_error(response: httpx.Response, field: str) -> None:
    assert_validation_error(response, field)


def assert_error_code(response: httpx.Response, code: str) -> None:
    payload = response.json()
    assert contains_validation_field(
        payload, code
    ), f"Expected error code {code!r}, got {payload!r}."


async def assert_model_exists(model_class: type[object], **filters: object) -> None:
    manager = getattr(model_class, "objects", None)
    if manager is None:
        raise AttributeError(f"{model_class!r} has no 'objects' manager.")
    found = await manager.filter(**filters).exists()
    assert found, f"Expected {model_class!r} matching {filters!r} to exist."


async def assert_model_count(model_class: type[object], expected: int, **filters: object) -> None:
    manager = getattr(model_class, "objects", None)
    if manager is None:
        raise AttributeError(f"{model_class!r} has no 'objects' manager.")
    queryset = manager.filter(**filters) if filters else manager.all()
    actual = await queryset.count()
    assert actual == expected, f"Expected {expected} {model_class!r} rows, got {actual}."


async def assert_queryset_count(queryset: object, expected: int) -> None:
    actual = await queryset.count()
    assert actual == expected, f"Expected queryset count {expected}, got {actual}."


def assert_field_value(model: object, field: str, expected: object) -> None:
    actual = getattr(model, field)
    assert actual == expected, f"Expected {field!r}={expected!r}, got {actual!r}."


def contains_validation_field(payload: object, field: str) -> bool:
    if isinstance(payload, dict):
        if field in payload:
            return True
        return any(contains_validation_field(value, field) for value in payload.values())
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return any(contains_validation_field(value, field) for value in payload)
    return False


def format_json_difference(actual: object, expected: object) -> str:
    return (
        "JSON response did not match.\n"
        f"Expected: {json.dumps(expected, sort_keys=True, default=str)}\n"
        f"Actual: {json.dumps(actual, sort_keys=True, default=str)}"
    )
