"""Shared base class and utilities for AI service modules."""

from __future__ import annotations

import logging
from typing import TypeVar

from openviper.ai.router import ModelRouter

logger = logging.getLogger(__name__)

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

T = TypeVar("T")


class AIServiceBase:
    """Base class for AI service wrappers that use :class:`ModelRouter`.

    Subclasses must set ``model_name`` and may override ``default_model``.
    """

    default_model: str = "llama3"

    def __init__(self, model_name: str = "") -> None:
        self.model_name = model_name or self.default_model
        self.router = ModelRouter()
        self.available = False
        self.init_router()

    def init_router(self) -> None:
        """Point the router at the configured model and verify availability."""
        try:
            self.router.set_model(self.model_name)
            self.router.get_provider()
            self.available = True
            logger.info("%s: using model '%s'", self.__class__.__name__, self.model_name)
        except Exception as exc:
            logger.warning(
                "%s: model '%s' not available - %s",
                self.__class__.__name__,
                self.model_name,
                exc,
            )
            self.available = False


def strip_ai_json_response(raw: str, *, is_array: bool = False) -> str:
    """Strip markdown fences and extract the first JSON object or array.

    Args:
        raw: Raw text returned by the AI model.
        is_array: When ``True``, look for ``[...]`` instead of ``{...}``.

    Returns:
        The extracted JSON string, or the stripped text if no delimiters found.
    """
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    open_ch, close_ch = ("[", "]") if is_array else ("{", "}")
    if open_ch in text and close_ch in text:
        text = text[text.find(open_ch) : text.rfind(close_ch) + 1]
    return text


def format_ingredients(ingredients: list[str], dietary_preferences: str = "") -> tuple[str, str]:
    """Build an ingredient string and optional dietary preference note.

    Returns:
        ``(ingredient_str, pref_note)`` where *pref_note* is empty when no
        preference is given.
    """
    ingredient_str = ", ".join(ingredients)
    pref_note = f" Dietary preference: {dietary_preferences}." if dietary_preferences else ""
    return ingredient_str, pref_note


def cached_factory[T](
    cache: dict[str, T], cls: type[T], model_name: str, default_model: str = ""
) -> T:
    """Return a cached instance of *cls* for *model_name*.

    If *model_name* is not yet in *cache*, a new instance is created and stored.
    """
    key = model_name or default_model or getattr(cls, "default_model", "llama3")
    if key not in cache:
        cache[key] = cls(model_name=key)
    return cache[key]
