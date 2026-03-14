"""AI-powered content moderation service."""

from __future__ import annotations

import logging
from typing import Any

from openviper.ai.router import ModelRouter

logger = logging.getLogger(__name__)


class ModerationResult:
    """AI moderation result."""

    def __init__(
        self,
        classification: str,
        confidence: float,
        reason: str,
        is_safe: bool,
    ):
        self.classification = classification
        self.confidence = confidence
        self.reason = reason
        self.is_safe = is_safe

    def to_dict(self) -> dict:
        return {
            "classification": self.classification,
            "confidence": self.confidence,
            "reason": self.reason,
            "is_safe": self.is_safe,
        }


class AIContentModerator:
    """Service for AI-powered content moderation.

    Uses :class:`~openviper.ai.router.ModelRouter` so the AI provider is
    selected by model ID at runtime — no direct provider coupling.

    Example::

        # Use the local Ollama model
        moderator = AIContentModerator(model_name="granite-code:3b")

        # Switch to Gemini without changing any other code
        moderator = AIContentModerator(model_name="gemini-2.0-flash")
    """

    def __init__(self, model_name: str = "granite-code:3b"):
        """Initialise the moderator.

        Args:
            model_name: Model ID to use for moderation.  Must be registered in
                ``settings.AI_PROVIDERS`` (the ProviderRegistry auto-populates
                from settings on first access).
        """
        self.model_name = model_name
        self._router = ModelRouter()
        self._available = False
        self._init_router()

    def _init_router(self) -> None:
        """Point the router at the configured model."""
        try:
            self._router.set_model(self.model_name)
            # Exercise the registry lookup now so failures surface early.
            self._router._get_provider()
            self._available = True
            logger.info("AIContentModerator: using model '%s'", self.model_name)
        except Exception as exc:
            logger.error("AIContentModerator: model '%s' not available — %s", self.model_name, exc)
            self._available = False

    async def moderate_content(self, content: str, threshold: float = 0.7) -> ModerationResult:
        """Moderate content using AI.

        Args:
            content: The content to moderate.
            threshold: Confidence threshold for flagging (default: 0.7).

        Returns:
            :class:`ModerationResult` with classification and confidence.
        """
        if not self._available:
            logger.warning("AIContentModerator: AI unavailable, defaulting to safe.")
            return ModerationResult(
                classification="safe",
                confidence=0.0,
                reason="AI moderation unavailable",
                is_safe=True,
            )

        try:
            result: dict[str, Any] = await self._router.moderate(content, temperature=0.1)
            # Honour the caller-supplied threshold on top of the base class default.
            is_safe = result["classification"] == "safe" or result["confidence"] < threshold
            return ModerationResult(
                classification=result["classification"],
                confidence=result["confidence"],
                reason=result["reason"],
                is_safe=is_safe,
            )
        except Exception as exc:
            logger.error("AIContentModerator: moderation failed — %s", exc)
            return ModerationResult(
                classification="safe",
                confidence=0.0,
                reason=f"Moderation error: {exc}",
                is_safe=True,
            )


# Global instance cache keyed by model name
_moderators: dict[str, AIContentModerator] = {}


def get_moderator(model_name: str = "granite-code:3b") -> AIContentModerator:
    """Return a cached :class:`AIContentModerator` for *model_name*."""
    if model_name not in _moderators:
        _moderators[model_name] = AIContentModerator(model_name=model_name)
    return _moderators[model_name]
