"""Tests for openviper/ai/exceptions.py – covers all constructor branches."""

from __future__ import annotations

from openviper.ai.exceptions import (
    AIError,
    AIException,
    ModelUnavailableError,
    ProviderNotAvailableError,
    ProviderNotConfiguredError,
)


def test_ai_error_is_alias():
    assert AIError is AIException


def test_provider_not_configured_error():
    exc = ProviderNotConfiguredError("openai")
    assert exc.provider == "openai"
    assert "openai" in str(exc)
    assert isinstance(exc, AIException)


def test_provider_not_available_error_no_reason():
    exc = ProviderNotAvailableError("anthropic")
    assert exc.provider == "anthropic"
    assert "anthropic" in str(exc)
    assert "Reason" not in str(exc)


def test_provider_not_available_error_with_reason():
    exc = ProviderNotAvailableError("anthropic", reason="missing API key")
    assert exc.provider == "anthropic"
    assert "missing API key" in str(exc)


def test_model_unavailable_error_no_reason():
    exc = ModelUnavailableError("gpt-4", "openai")
    assert exc.model == "gpt-4"
    assert exc.provider == "openai"
    assert "gpt-4" in str(exc)
    assert "openai" in str(exc)
    assert "Reason" not in str(exc)


def test_model_unavailable_error_with_reason():
    exc = ModelUnavailableError("gpt-4", "openai", reason="quota exceeded")
    assert exc.model == "gpt-4"
    assert exc.provider == "openai"
    assert "quota exceeded" in str(exc)
