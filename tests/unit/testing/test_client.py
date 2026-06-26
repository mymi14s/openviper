"""Tests for the OpenViper async test client."""

from __future__ import annotations

import pytest

from openviper.testing.client import OpenViperTestClient
from openviper.testing.settings import override_openviper_settings


async def test_client_get_returns_200_for_registered_route(minimal_app, allowed_hosts) -> None:
    with override_openviper_settings(ALLOWED_HOSTS=allowed_hosts):
        async with OpenViperTestClient(minimal_app) as client:
            response = await client.get("/status")

    assert response.status_code == 200


async def test_client_get_returns_expected_json_body(minimal_app, allowed_hosts) -> None:
    with override_openviper_settings(ALLOWED_HOSTS=allowed_hosts):
        async with OpenViperTestClient(minimal_app) as client:
            response = await client.get("/status")

    assert response.json() == {"status": "ok"}


async def test_client_returns_404_for_unknown_route(minimal_app, allowed_hosts) -> None:
    with override_openviper_settings(ALLOWED_HOSTS=allowed_hosts):
        async with OpenViperTestClient(minimal_app) as client:
            response = await client.get("/does-not-exist")

    assert response.status_code == 404


async def test_client_clears_internal_reference_after_context_exit(
    minimal_app, allowed_hosts
) -> None:
    wrapper = OpenViperTestClient(minimal_app)

    with override_openviper_settings(ALLOWED_HOSTS=allowed_hosts):
        async with wrapper:
            pass

    assert wrapper.client is None


async def test_client_accepts_custom_base_url(minimal_app, allowed_hosts) -> None:
    with override_openviper_settings(ALLOWED_HOSTS=allowed_hosts):
        async with OpenViperTestClient(minimal_app, base_url="http://api.test") as client:
            response = await client.get("/status")

    assert response.status_code == 200


async def test_client_response_includes_json_content_type(minimal_app, allowed_hosts) -> None:
    with override_openviper_settings(ALLOWED_HOSTS=allowed_hosts):
        async with OpenViperTestClient(minimal_app) as client:
            response = await client.get("/status")

    assert "application/json" in response.headers.get("content-type", "")


@pytest.mark.parametrize("method", ["get", "post", "put", "patch", "delete"])
async def test_client_supports_standard_http_method(
    method: str, minimal_app, allowed_hosts
) -> None:
    with override_openviper_settings(ALLOWED_HOSTS=allowed_hosts):
        async with OpenViperTestClient(minimal_app) as client:
            caller = getattr(client, method)
            response = await caller("/m")

    assert response.status_code == 200
