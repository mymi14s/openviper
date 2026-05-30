"""Tests for OpenViper testing assertions."""

from __future__ import annotations

import httpx
import pytest

from openviper.testing.assertions import (
    assert_cookie,
    assert_error_code,
    assert_field_error,
    assert_field_value,
    assert_header,
    assert_json_contains,
    assert_json_path,
    assert_redirects,
    assert_response_json,
    assert_status,
    assert_validation_error,
    contains_validation_field,
    format_json_difference,
)

# ── assert_status ──────────────────────────────────────────────────────────


def test_assert_status_accepts_matching_status() -> None:
    response = httpx.Response(201, json={"ok": True})

    assert_status(response, 201)


def test_assert_status_reports_response_body() -> None:
    response = httpx.Response(400, text="bad request")

    with pytest.raises(AssertionError, match="bad request"):
        assert_status(response, 200)


# ── assert_header ──────────────────────────────────────────────────────────


def test_assert_header_detects_present_header() -> None:
    response = httpx.Response(200, headers={"X-Request-Id": "abc123"})

    assert_header(response, "X-Request-Id")


def test_assert_header_validates_header_value() -> None:
    response = httpx.Response(200, headers={"Content-Type": "application/json"})

    assert_header(response, "Content-Type", "application/json")


def test_assert_header_rejects_wrong_value() -> None:
    response = httpx.Response(200, headers={"Content-Type": "text/html"})

    with pytest.raises(AssertionError, match="application/json"):
        assert_header(response, "Content-Type", "application/json")


def test_assert_header_fails_when_header_missing() -> None:
    response = httpx.Response(200)

    with pytest.raises(AssertionError, match="X-Missing"):
        assert_header(response, "X-Missing")


# ── assert_cookie ──────────────────────────────────────────────────────────


def test_assert_cookie_detects_present_cookie() -> None:
    request = httpx.Request("GET", "https://example.com/")
    response = httpx.Response(
        200,
        headers=[("set-cookie", "session=abc; Path=/")],
        request=request,
    )

    assert_cookie(response, "session")


def test_assert_cookie_fails_when_cookie_missing() -> None:
    request = httpx.Request("GET", "https://example.com/")
    response = httpx.Response(200, request=request)

    with pytest.raises(AssertionError, match="token"):
        assert_cookie(response, "token")


# ── assert_response_json ──────────────────────────────────────────────────


def test_assert_response_json_matches_exact_payload() -> None:
    response = httpx.Response(200, json={"id": 1, "name": "Ada"})

    assert_response_json(response, {"id": 1, "name": "Ada"})


def test_assert_response_json_reports_mismatch() -> None:
    response = httpx.Response(200, json={"id": 2})

    with pytest.raises(AssertionError, match="JSON response did not match"):
        assert_response_json(response, {"id": 1})


# ── assert_json_contains ──────────────────────────────────────────────────


def test_assert_json_contains_checks_subset() -> None:
    response = httpx.Response(200, json={"id": 1, "name": "Ada"})

    assert_json_contains(response, {"name": "Ada"})


def test_assert_json_contains_rejects_missing_key() -> None:
    response = httpx.Response(200, json={"id": 1})

    with pytest.raises(AssertionError, match="JSON response did not contain"):
        assert_json_contains(response, {"name": "Ada"})


def test_assert_json_contains_rejects_wrong_value() -> None:
    response = httpx.Response(200, json={"name": "Bob"})

    with pytest.raises(AssertionError, match="name"):
        assert_json_contains(response, {"name": "Ada"})


def test_assert_json_contains_rejects_non_dict_payload() -> None:
    response = httpx.Response(200, json=[1, 2, 3])

    with pytest.raises(AssertionError, match="object"):
        assert_json_contains(response, {"id": 1})


# ── assert_redirects ──────────────────────────────────────────────────────


def test_assert_redirects_accepts_valid_redirect() -> None:
    response = httpx.Response(302, headers={"location": "/login"})

    assert_redirects(response)


def test_assert_redirects_validates_location() -> None:
    response = httpx.Response(301, headers={"location": "/new-url"})

    assert_redirects(response, "/new-url")


def test_assert_redirects_rejects_wrong_location() -> None:
    response = httpx.Response(302, headers={"location": "/old"})

    with pytest.raises(AssertionError, match="/new"):
        assert_redirects(response, "/new")


def test_assert_redirects_rejects_non_redirect_status() -> None:
    response = httpx.Response(200)

    with pytest.raises(AssertionError, match="redirect"):
        assert_redirects(response)


def test_assert_redirects_accepts_all_redirect_codes() -> None:
    for code in (301, 302, 303, 307, 308):
        response = httpx.Response(code, headers={"location": "/target"})
        assert_redirects(response)


# ── assert_json_path ──────────────────────────────────────────────────────


def test_assert_json_path_finds_nested_value() -> None:
    payload = {"user": {"profile": {"name": "Ada"}}}

    assert_json_path(payload, "user.profile.name", "Ada")


def test_assert_json_path_rejects_wrong_value() -> None:
    payload = {"user": {"name": "Ada"}}

    with pytest.raises(AssertionError, match="Ada"):
        assert_json_path(payload, "user.name", "Bob")


def test_assert_json_path_raises_on_missing_path() -> None:
    payload = {"user": {"name": "Ada"}}

    with pytest.raises(AssertionError, match="missing"):
        assert_json_path(payload, "user.email", "x@example.com")


# ── assert_validation_error / assert_field_error / assert_error_code ──────


def test_assert_validation_error_finds_field_in_dict() -> None:
    response = httpx.Response(422, json={"errors": {"email": ["required"]}})

    assert_validation_error(response, "email")


def test_assert_validation_error_finds_field_in_nested_payload() -> None:
    response = httpx.Response(422, json={"detail": {"errors": {"name": ["invalid"]}}})

    assert_validation_error(response, "name")


def test_assert_validation_error_fails_when_field_missing() -> None:
    response = httpx.Response(422, json={"errors": {"email": ["required"]}})

    with pytest.raises(AssertionError, match="username"):
        assert_validation_error(response, "username")


def test_assert_field_error_delegates_to_validation_error() -> None:
    response = httpx.Response(422, json={"errors": {"password": ["too short"]}})

    assert_field_error(response, "password")


def test_assert_error_code_finds_key_in_payload() -> None:
    response = httpx.Response(400, json={"errors": {"RATE_LIMITED": ["too many requests"]}})

    assert_error_code(response, "RATE_LIMITED")


def test_assert_error_code_fails_when_code_missing() -> None:
    response = httpx.Response(400, json={"errors": {"NOT_FOUND": ["resource missing"]}})

    with pytest.raises(AssertionError, match="RATE_LIMITED"):
        assert_error_code(response, "RATE_LIMITED")


# ── assert_field_value ────────────────────────────────────────────────────


def test_assert_field_value_accepts_matching_value() -> None:

    class Obj:
        name = "Ada"

    assert_field_value(Obj(), "name", "Ada")


def test_assert_field_value_rejects_mismatch() -> None:

    class Obj:
        name = "Bob"

    with pytest.raises(AssertionError, match="Ada"):
        assert_field_value(Obj(), "name", "Ada")


# ── contains_validation_field ─────────────────────────────────────────────


def test_contains_validation_field_finds_key_in_dict() -> None:
    assert contains_validation_field({"email": ["required"]}, "email") is True


def test_contains_validation_field_finds_key_in_nested_dict() -> None:
    payload = {"detail": {"errors": {"name": ["invalid"]}}}
    assert contains_validation_field(payload, "name") is True


def test_contains_validation_field_finds_key_in_list() -> None:
    payload = [{"email": ["required"]}, {"name": ["invalid"]}]
    assert contains_validation_field(payload, "name") is True


def test_contains_validation_field_returns_false_for_missing_key() -> None:
    assert contains_validation_field({"email": ["required"]}, "username") is False


def test_contains_validation_field_ignores_string_sequences() -> None:
    assert contains_validation_field("just a string", "anything") is False


# ── format_json_difference ────────────────────────────────────────────────


def test_format_json_difference_includes_expected_and_actual() -> None:
    message = format_json_difference({"id": 2}, {"id": 1})

    assert "JSON response did not match" in message
    assert '"id": 1' in message
    assert '"id": 2' in message
