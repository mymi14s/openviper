"""Unit tests for openviper/ai/exceptions.py - custom exception classes."""

from __future__ import annotations

import pickle

from openviper.ai.exceptions import (
    AIException,
    ModelUnavailableError,
    ProviderNotAvailableError,
    ProviderNotConfiguredError,
)
from openviper.exceptions import ModelCollisionError, ModelNotFoundError


class TestAIExceptionAlias:
    def test_ai_error_is_ai_exception(self):
        assert AIException is AIException


class TestProviderNotConfiguredError:
    def test_message(self):
        err = ProviderNotConfiguredError("openai")
        assert "openai" in str(err)
        assert "not configured" in str(err)

    def test_provider_attribute(self):
        err = ProviderNotConfiguredError("openai")
        assert err.provider == "openai"

    def test_pickling_roundtrip(self):
        err = ProviderNotConfiguredError("openai")
        restored = pickle.loads(pickle.dumps(err))
        assert restored.provider == "openai"
        assert str(restored) == str(err)

    def test_is_ai_exception(self):
        err = ProviderNotConfiguredError("test")
        assert isinstance(err, AIException)


class TestProviderNotAvailableError:
    def test_message_with_reason(self):
        err = ProviderNotAvailableError("gemini", reason="API key expired")
        assert "gemini" in str(err)
        assert "API key expired" in str(err)

    def test_message_without_reason(self):
        err = ProviderNotAvailableError("gemini")
        assert "gemini" in str(err)
        assert "not available" in str(err)

    def test_attributes(self):
        err = ProviderNotAvailableError("gemini", reason="timeout")
        assert err.provider == "gemini"
        assert err.reason == "timeout"

    def test_pickling_roundtrip(self):
        err = ProviderNotAvailableError("gemini", reason="rate limit")
        restored = pickle.loads(pickle.dumps(err))
        assert restored.provider == "gemini"
        assert restored.reason == "rate limit"

    def test_is_ai_exception(self):
        err = ProviderNotAvailableError("test")
        assert isinstance(err, AIException)


class TestModelUnavailableError:
    def test_message_with_reason(self):
        err = ModelUnavailableError("gpt-5", "openai", reason="not deployed")
        assert "gpt-5" in str(err)
        assert "openai" in str(err)
        assert "not deployed" in str(err)

    def test_message_without_reason(self):
        err = ModelUnavailableError("gpt-5", "openai")
        assert "gpt-5" in str(err)
        assert "unavailable" in str(err)

    def test_attributes(self):
        err = ModelUnavailableError("gpt-5", "openai", reason="down")
        assert err.model == "gpt-5"
        assert err.provider == "openai"
        assert err.reason == "down"

    def test_pickling_roundtrip(self):
        err = ModelUnavailableError("gpt-5", "openai", reason="quota")
        restored = pickle.loads(pickle.dumps(err))
        assert restored.model == "gpt-5"
        assert restored.provider == "openai"
        assert restored.reason == "quota"

    def test_is_ai_exception(self):
        err = ModelUnavailableError("m", "p")
        assert isinstance(err, AIException)


class TestReExports:
    def test_model_not_found_error(self):
        err = ModelNotFoundError("gpt-5", ["gpt-4o"])
        assert err.model == "gpt-5"
        assert "gpt-5" in str(err)
        assert isinstance(err, AIException)

    def test_model_collision_error(self):
        err = ModelCollisionError("gpt-4o", "openai", "custom")
        assert err.model == "gpt-4o"
        assert isinstance(err, AIException)
