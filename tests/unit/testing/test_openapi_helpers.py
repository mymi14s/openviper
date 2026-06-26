"""Tests for OpenViper testing OpenAPI assertion helpers."""

from __future__ import annotations

import pytest

from openviper.testing.openapi import (
    assert_openapi_operation,
    assert_openapi_path,
    assert_request_schema,
    assert_response_schema,
    get_operation,
)

SAMPLE_SCHEMA: dict[str, object] = {
    "paths": {
        "/users": {
            "get": {
                "responses": {"200": {"description": "OK"}},
            },
            "post": {
                "requestBody": {"content": {"application/json": {"schema": {}}}},
                "responses": {"201": {"description": "Created"}},
            },
        },
        "/users/{id}": {
            "get": {
                "responses": {"200": {"description": "OK"}, "404": {"description": "Not found"}},
            },
        },
    }
}


# ── assert_openapi_path ────────────────────────────────────────────────────


def test_assert_openapi_path_accepts_existing_path() -> None:
    assert_openapi_path(SAMPLE_SCHEMA, "/users")


def test_assert_openapi_path_accepts_parameterized_path() -> None:
    assert_openapi_path(SAMPLE_SCHEMA, "/users/{id}")


def test_assert_openapi_path_rejects_missing_path() -> None:
    with pytest.raises(AssertionError, match="/orders"):
        assert_openapi_path(SAMPLE_SCHEMA, "/orders")


def test_assert_openapi_path_rejects_schema_without_paths() -> None:
    with pytest.raises(AssertionError, match="paths"):
        assert_openapi_path({}, "/users")


# ── assert_openapi_operation ──────────────────────────────────────────────


def test_assert_openapi_operation_accepts_existing_method() -> None:
    assert_openapi_operation(SAMPLE_SCHEMA, "/users", "GET")


def test_assert_openapi_operation_accepts_lowercase_method() -> None:
    assert_openapi_operation(SAMPLE_SCHEMA, "/users", "post")


def test_assert_openapi_operation_rejects_missing_method() -> None:
    with pytest.raises(AssertionError, match="DELETE"):
        assert_openapi_operation(SAMPLE_SCHEMA, "/users", "DELETE")


def test_assert_openapi_operation_rejects_missing_path() -> None:
    with pytest.raises(AssertionError, match="/orders"):
        assert_openapi_operation(SAMPLE_SCHEMA, "/orders", "GET")


# ── assert_response_schema ────────────────────────────────────────────────


def test_assert_response_schema_accepts_existing_status_code() -> None:
    assert_response_schema(SAMPLE_SCHEMA, "/users", "GET", 200)


def test_assert_response_schema_accepts_post_response() -> None:
    assert_response_schema(SAMPLE_SCHEMA, "/users", "POST", 201)


def test_assert_response_schema_rejects_missing_status_code() -> None:
    with pytest.raises(AssertionError, match="404"):
        assert_response_schema(SAMPLE_SCHEMA, "/users", "GET", 404)


def test_assert_response_schema_rejects_operation_without_responses() -> None:
    schema: dict[str, object] = {"paths": {"/ping": {"get": {}}}}
    with pytest.raises(AssertionError, match="responses"):
        assert_response_schema(schema, "/ping", "GET", 200)


# ── assert_request_schema ────────────────────────────────────────────────


def test_assert_request_schema_accepts_existing_body() -> None:
    assert_request_schema(SAMPLE_SCHEMA, "/users", "POST")


def test_assert_request_schema_rejects_missing_body() -> None:
    with pytest.raises(AssertionError, match="request"):
        assert_request_schema(SAMPLE_SCHEMA, "/users", "GET")


# ── get_operation ─────────────────────────────────────────────────────────


def test_get_operation_returns_operation_dict() -> None:
    operation = get_operation(SAMPLE_SCHEMA, "/users", "GET")
    assert isinstance(operation, dict)
    assert "responses" in operation


def test_get_operation_rejects_missing_path() -> None:
    with pytest.raises(AssertionError, match="/missing"):
        get_operation(SAMPLE_SCHEMA, "/missing", "GET")


def test_get_operation_rejects_missing_method() -> None:
    with pytest.raises(AssertionError, match="DELETE"):
        get_operation(SAMPLE_SCHEMA, "/users", "DELETE")


def test_get_operation_rejects_schema_without_paths() -> None:
    with pytest.raises(AssertionError, match="paths"):
        get_operation({}, "/users", "GET")
